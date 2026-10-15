"""Caption proofreading by Claude Code (the user's own `claude` CLI, no API).

Claude can't hear audio, so the speech model keeps every word's timing; Claude
only reads the clip's words in context and returns spelling/hearing fixes
(names, Bible references, Swahili words, things that make no sense). Fixes are
stored like hand edits (ClipEdit.word_edits, keyed by the word's source start)
so the user reviews and undoes them the same way.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from . import store
from .timeline import word_key

PROMPT = """You proofread on-screen captions for a short video clip cut from a sermon/talk.
The words came from a speech-recognition model, which mishears names, Bible
references, numbers, non-English (often Swahili) words, and sometimes writes
nonsense. Below is every word of the clip as KEY<TAB>WORD, in order.{context}

Return ONLY a JSON object, no prose:
{{"edits": {{"<KEY>": "<corrected text>", ...}}}}

Rules:
- Include only words you are confident are wrong. Leave correct words out.
- Keep it a caption of what was SAID: fix spelling and mishearing, never
  rephrase, summarize or translate. Keep Swahili as Swahili, spelled properly.
- A correction may hold several words if one recognized word was really
  several (e.g. "Timothy4.15" -> "1 Timothy 4:15"), and "" deletes a word that
  is pure noise or a stutter the speech model invented.
- Bible references: standard form, e.g. "1 Timothy 4:15".

WORDS:
{words}"""


def _clip_words(job_dir: Path, start: float, end: float) -> list[dict]:
    diarize = json.loads((job_dir / "diarize.json").read_text())["data"]
    return [
        {"key": word_key(w["start"]), "word": w["word"]}
        for seg in diarize["segments"]
        for w in seg.get("words", [])
        if "start" in w and start <= w["start"] < end
    ]


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Claude didn't return JSON.")
    return json.loads(m.group(0))


def proofread(job_dir: Path, clip_idx: int, claude: str, title: str | None = None) -> dict:
    score = json.loads((job_dir / "score.json").read_text())["data"]
    clip = score["clips"][clip_idx]
    edit = store.edit_for_clip(job_dir, clip_idx, clip)
    words = _clip_words(job_dir, edit.start, edit.end)
    if not words:
        raise ValueError("This clip has no transcribed words.")
    context = f"\nThe video is titled: {title}." if title else ""
    prompt = PROMPT.format(context=context, words="\n".join(f"{w['key']}\t{w['word']}" for w in words))

    proc = subprocess.run(
        [claude, "-p", "--output-format", "json", "--max-turns", "1"],
        input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "claude failed")[-400:])
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(str(envelope.get("result") or "Claude returned an error."))
    suggested = _extract_json(envelope.get("result", "")).get("edits", {}) or {}

    known = {w["key"]: w["word"] for w in words}
    applied = {}
    for key, text in suggested.items():
        if key in known and isinstance(text, str) and text.strip() != known[key].strip():
            applied[key] = text.strip()
    # The user's own edits win over Claude's.
    new = {k: v for k, v in applied.items() if k not in edit.word_edits}
    edit.word_edits = {**new, **edit.word_edits}
    edits = store.load(job_dir)
    edits[str(clip_idx)] = edit
    store.save(job_dir, edits)
    return {"changed": len(new), "suggested": new, "edit": edit.to_json()}
