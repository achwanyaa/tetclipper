"""transcript.md: a compact text view of a clip for Claude Code.

Claude edits spec.json, but reading hundreds of word objects to find "the
part about Goliath" is wasteful. This file lists the clip phrase by phrase
with source times and word indices, so Claude can find a span by reading
~1 line per sentence, then edit `words[i]`, `cuts` or `effects` precisely.
"""

from __future__ import annotations

import json
from pathlib import Path

PHRASE_PAUSE = 0.6
PHRASE_MAX_WORDS = 14


def _phrases(words: list[dict]) -> list[list[int]]:
    out: list[list[int]] = []
    cur: list[int] = []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (
            nxt is None
            or len(cur) >= PHRASE_MAX_WORDS
            or w["text"].rstrip().endswith((".", "!", "?"))
            or nxt["start"] - w["end"] > PHRASE_PAUSE
            or nxt.get("speaker") != w.get("speaker")
        ):
            out.append(cur)
            cur = []
    return out


def _events(job_dir: Path, start: float, end: float) -> list[str]:
    path = Path(job_dir) / "events.json"
    if not path.exists():
        return []
    timeline = json.loads(path.read_text(encoding="utf-8"))["data"].get("timeline", [])
    return [
        f"{e['start']:.2f} {e['type']}"
        for e in timeline
        if e.get("type") not in ("pause", "energy") and start <= e.get("start", -1) < end
    ][:40]


def render(job_dir: Path, spec: dict) -> str:
    src = spec["source"]
    words = spec.get("words", [])
    cuts = spec.get("cuts", [])

    def in_cut(t: float) -> bool:
        return any(c["start"] <= t < c["end"] for c in cuts)

    lines = [
        f"# {spec.get('title') or 'clip'}",
        f"range {src['start']:.2f}–{src['end']:.2f} s (source seconds)  ·  "
        f"captions {spec.get('captions', {}).get('style', '?')}  ·  "
        f"intro {'yes' if spec.get('intro') else 'none'}  ·  cuts {len(cuts)}",
        "",
        "Format: [start–end] speaker #first-last: text   (~~struck~~ = hidden word, ✂ = inside a cut)",
        "",
    ]
    for idx in _phrases(words):
        first, last = words[idx[0]], words[idx[-1]]
        text = " ".join(
            f"~~{words[i]['text']}~~" if words[i].get("hidden") else words[i]["text"] for i in idx
        )
        mark = " ✂" if in_cut((first["start"] + last["end"]) / 2) else ""
        lines.append(
            f"[{first['start']:.2f}–{last['end']:.2f}] {first.get('speaker', '')} #{idx[0]}-{idx[-1]}{mark}: {text}"
        )
    doubts = [d for d in spec.get("doubts", []) if d["to"] < len(words)]
    if doubts:
        lines += ["", "To check (the speech model may have misheard; Swahili/Sheng often comes out as English-sounding words):"]
        for d in doubts:
            span = " ".join(w["text"] for w in words[d["from"] : d["to"] + 1] if not w.get("hidden"))
            alt = f' · Swahili listen heard: "{d["alt"]}"' if d.get("alt") else ""
            lines.append(f'?? [{words[d["from"]]["start"]:.2f}] #{d["from"]}-{d["to"]} "{span}" ({d["reason"]}){alt}')
    events = _events(job_dir, src["start"], src["end"])
    if events:
        lines += ["", "Audio events: " + ", ".join(events)]
    return "\n".join(lines) + "\n"


def write(job_dir: Path, clip_idx: int, spec: dict) -> Path:
    from .store import clip_dir

    path = clip_dir(job_dir, clip_idx) / "transcript.md"
    path.write_text(render(job_dir, spec), encoding="utf-8")
    return path
