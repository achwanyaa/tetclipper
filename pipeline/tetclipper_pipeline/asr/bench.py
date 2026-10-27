"""The ears test: which speech model hears these sermons best.

Claude can fix a transcript but can't hear the audio, so captions are only as
good as the speech model's ears. This runs candidate models over short pieces
of the user's own sermons and scores them against words the user checked by
ear:

  reference  spans the user confirmed ("caption is right"), took a Swahili
             reading for, or retyped, read from a clip's edit history
             (`from_history`); plus gold segments the user transcribed
  modes      sw    forced Swahili, the second listen's settings (hotwords)
             en    forced English with the first pass's hints (initial
                   prompt + hotwords): what clips get today
             auto  the model picks the language, same hints
  scores     word and character error rates, overall and on the Swahili and
             Sheng words alone (asr/swahili.py), and seconds per minute of
             audio

Every model goes through the second listen's own call (spec/doubts.hear), so
a winner drops straight in. Paza and Jacaranda ship as transformers
checkpoints: `ensure_converted` turns them into CTranslate2 once, under
models/ct2. Runs on a Modal GPU (`asr_bench` in modal_app.py) or here.
"""

from __future__ import annotations

import gc
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..spec import doubts, store
from ..spec.glossary import norm
from . import swahili

RATE = 16000
CONTEXT_WORDS = 2  # either side of a retyped word: one word alone is too short to hear
MIN_SEC = 4.0  # shortest piece worth hearing; spans grow to this many seconds of whole words
MAX_GAP_SEC = 1.2  # …but not across a longer pause
MODES = ("sw", "en", "auto")
KINDS = ("retyped", "swahili", "checked", "gold")  # how the user checked a span, most telling first


@dataclass(frozen=True)
class Candidate:
    model: str  # faster-whisper size name or Hugging Face repo
    label: str
    convert: bool = False  # a transformers checkpoint: convert to CTranslate2 once


CANDIDATES = {
    "turbo": Candidate("large-v3-turbo", "Whisper large-v3-turbo (today's model)"),
    "large-v3": Candidate("large-v3", "Whisper large-v3 (full size)"),
    "paza": Candidate("microsoft/paza-whisper-large-v3-turbo", "Microsoft Paza (turbo tuned on Kenyan languages)", convert=True),
    "jacaranda": Candidate("Jacaranda-Health/ASR-STT", "Jacaranda Health Swahili/English (medium tuned)", convert=True),
    # Gated on Hugging Face: needs HF_TOKEN from an account that accepted its terms.
    "sunbird": Candidate("Sunbird/faster-whisper-51-african-languages", "Sunbird (large-v3 tuned on 51 African languages)"),
}
DEFAULT_MODELS = ("turbo", "large-v3", "paza", "jacaranda")


# ---------- the reference: what the user checked by ear ----------

def _visible_text(words: list[dict], a: int, b: int) -> str:
    return " ".join(w["text"] for w in words[a : b + 1] if not w.get("hidden") and w["text"].strip())


def _context(words: list[dict], i: int) -> tuple[int, int]:
    """A retyped word plus up to CONTEXT_WORDS neighbours each side, within the sentence."""
    a = b = i
    for _ in range(CONTEXT_WORDS):
        if a > 0 and words[a - 1]["text"].rstrip()[-1:] not in ".!?" and words[a]["start"] - words[a - 1]["end"] < 0.6:
            a -= 1
        if b + 1 < len(words) and words[b]["text"].rstrip()[-1:] not in ".!?" and words[b + 1]["start"] - words[b]["end"] < 0.6:
            b += 1
    return a, b


def _widen(words: list[dict], a: int, b: int) -> tuple[int, int, float, float]:
    """Grow a span to MIN_SEC of whole words and cut the audio halfway between
    words, so every word in the audio is in the reference. Short pieces make
    every model guess (and leak the hint prompt: "Yaani you can" came back as
    "Sasa kwa hivyo, I- mean"); stray halves of neighbours read as errors."""
    def dur() -> float:
        return words[b]["end"] - words[a]["start"]

    while dur() < MIN_SEC:
        grew = False
        if a > 0 and words[a]["start"] - words[a - 1]["end"] < MAX_GAP_SEC:
            a, grew = a - 1, True
        if dur() < MIN_SEC and b + 1 < len(words) and words[b + 1]["start"] - words[b]["end"] < MAX_GAP_SEC:
            b, grew = b + 1, True
        if not grew:
            break
    lo = words[a]["start"] - doubts.PAD_SEC
    if a > 0:
        lo = max(lo, (words[a - 1]["end"] + words[a]["start"]) / 2)
    hi = words[b]["end"] + doubts.PAD_SEC
    if b + 1 < len(words):
        hi = min(hi, (words[b]["end"] + words[b + 1]["start"]) / 2)
    return a, b, max(0.0, lo), hi


def from_history(job_dir: Path, clip: int = 0) -> list[dict]:
    """Spans of one clip the user checked by ear, with what was really said.

    Walks the clip's saved versions: a doubt that disappears on "caption is
    right" or "use Swahili reading" is a checked span, and a "fix word" edit
    is a retyped span (with a little context). Each span keeps the text from
    the user's last edit of it, so Claude's later guesses never leak in."""
    job_dir = Path(job_dir)
    history = sorted((store.clip_dir(job_dir, clip) / "history").glob("*.json"))
    found: dict[tuple[int, int, int], dict] = {}  # (epoch, from, to) → span
    original: dict[int, dict] = {}  # word index → the word before the user first touched it
    prev_words: list[dict] | None = None
    prev_doubts: set[tuple[int, int]] = set()
    epoch = 0  # bumps when the word count changes and indices stop lining up

    def snap(a: int, b: int, kind: str, words: list[dict], before: list[dict]) -> None:
        old = found.get((epoch, a, b))
        if old is None:
            a, b = _widen(words, a, b)[:2]
            # Overlapping spans become one; a retyped one says the most.
            while overlap := [k for k in found if k[0] == epoch and k[1] <= b and a <= k[2]]:
                for k in overlap:
                    a, b = min(a, k[1]), max(b, k[2])
                    kind = min(kind, found.pop(k)["kind"], key=KINDS.index)
        for i in range(a, b + 1):
            original.setdefault(i, before[i])
        lo, hi = _widen(words, a, b)[2:]
        found[(epoch, a, b)] = {
            "kind": old["kind"] if old else kind,
            "start": lo, "end": hi,
            "ref": _visible_text(words, a, b),
            "heard": _visible_text([original[i] for i in range(a, b + 1)], 0, b - a),
        }

    for path in history:
        spec = json.loads(path.read_text(encoding="utf-8"))
        reason_file = path.with_suffix(".reason")
        reason = reason_file.read_text(encoding="utf-8") if reason_file.exists() else ""
        words = spec.get("words") or []
        now_doubts = {(d["from"], d["to"]) for d in spec.get("doubts") or []}
        if prev_words is not None and len(prev_words) != len(words):
            epoch += 1
            original = {}
        elif prev_words is not None:
            if reason.startswith(("caption is right", "use Swahili reading")):
                kind = "checked" if reason.startswith("caption") else "swahili"
                for a, b in prev_doubts - now_doubts:
                    snap(a, b, kind, words, prev_words)
            elif reason.startswith("fix word"):
                for i, (old, new) in enumerate(zip(prev_words, words)):
                    if old["text"] == new["text"] and bool(old.get("hidden")) == bool(new.get("hidden")):
                        continue
                    inside = next((k for k in found if k[0] == epoch and k[1] <= i <= k[2]), None)
                    if inside:
                        snap(inside[1], inside[2], "", words, prev_words)
                        continue
                    # Fixes next to an earlier span grow it ("to go to work on a").
                    snap(*_context(words, i), "retyped", words, prev_words)
        prev_words, prev_doubts = words, now_doubts

    out = []
    for item in sorted(found.values(), key=lambda s: s["start"]):
        if not item["ref"] and not item["heard"]:
            continue
        out.append({"id": f"{job_dir.name}:{clip}:{len(out)}", "audio": str(job_dir / "audio16k.wav"),
                    "start": round(item["start"], 3), "end": round(item["end"], 3),
                    **{k: item[k] for k in ("kind", "ref", "heard")}})
    return out


def attach_audio(segments: list[dict]) -> list[dict]:
    """Each segment with its samples as 16-bit PCM bytes (`pcm`), ready to send to the GPU."""
    import numpy as np

    from .stage import load_audio

    cache: dict[str, object] = {}
    out = []
    for seg in segments:
        audio = cache.get(seg["audio"])
        if audio is None:
            audio = cache[seg["audio"]] = load_audio(Path(seg["audio"]))
        piece = audio[int(seg["start"] * RATE) : int(seg["end"] * RATE)]
        out.append({**seg, "pcm": (np.clip(piece, -1, 1) * 32767).astype(np.int16).tobytes()})
    return out


# ---------- the models ----------

def ensure_converted(cid: str) -> Path:
    """A transformers Whisper checkpoint as a CTranslate2 folder faster-whisper
    can load, made once. Saves tokenizer.json too: without it faster-whisper
    falls back to whisper-tiny's tokenizer, whose ids don't match these models."""
    from .stage import _point_caches_at_home

    out = config.models_dir() / "ct2" / cid
    if (out / "model.bin").exists() and (out / "tokenizer.json").exists():
        return out
    _point_caches_at_home()
    from ctranslate2.converters import TransformersConverter
    from huggingface_hub import snapshot_download
    from transformers import WhisperTokenizerFast

    local = snapshot_download(CANDIDATES[cid].model, allow_patterns=["*.json", "*.txt", "model.safetensors"])
    part = out.with_name(cid + ".part")
    shutil.rmtree(part, ignore_errors=True)
    part.parent.mkdir(parents=True, exist_ok=True)
    TransformersConverter(local, copy_files=["preprocessor_config.json"], load_as_float16=True).convert(
        str(part), quantization="float16", force=True)
    WhisperTokenizerFast.from_pretrained(local).backend_tokenizer.save(str(part / "tokenizer.json"))
    shutil.rmtree(out, ignore_errors=True)
    part.rename(out)
    return out


def model_ref(cid: str) -> str:
    cand = CANDIDATES[cid]
    return str(ensure_converted(cid)) if cand.convert else cand.model


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(segments: list[dict], models: list[str], modes: list[str], hotwords: str = "",
        prompt: str | None = None) -> list[dict]:
    """Every model × mode over every segment (with `pcm`): one row per hearing."""
    import numpy as np

    rows: list[dict] = []
    for cid in models:
        t0 = time.monotonic()
        try:
            model = doubts.load_model(model_ref(cid))
        except Exception as err:  # noqa: BLE001 — one model failing mustn't sink the test
            _log(f"{cid}: could not load ({err})")
            rows.append({"model": cid, "mode": None, "id": None, "text": "", "secs": 0.0, "error": f"could not load: {err}"})
            continue
        _log(f"{cid}: loaded in {time.monotonic() - t0:.0f}s")
        for mode in modes:
            for seg in segments:
                clip = np.frombuffer(seg["pcm"], np.int16).astype(np.float32) / 32768.0
                t1 = time.monotonic()
                try:
                    text, error = doubts.hear(model, clip, None if mode == "auto" else mode, hotwords,
                                              None if mode == "sw" else prompt), None
                except Exception as err:  # noqa: BLE001 — e.g. a language code faster-whisper doesn't know
                    text, error = "", str(err)
                rows.append({"model": cid, "mode": mode, "id": seg["id"], "text": text,
                             "secs": round(time.monotonic() - t1, 3), "error": error})
            _log(f"{cid} {mode}: done")
        del model
        gc.collect()
    return rows


# ---------- scoring ----------

def align(ref: list[str], hyp: list[str]) -> list[tuple[str | None, str | None]]:
    """Minimum-edit alignment: (ref word, heard word) pairs; None marks a gap."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1, cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    pairs: list[tuple[str | None, str | None]] = []
    i, j = n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            pairs.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            pairs.append((ref[i - 1], None))
            i -= 1
        else:
            pairs.append((None, hyp[j - 1]))
            j -= 1
    return pairs[::-1]


def _edits(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def score(ref: str, heard: str) -> dict:
    """Word errors (substitutions + deletions + insertions), the same on the
    Swahili/Sheng reference words alone (substitutions + deletions), and
    character errors."""
    r, h = norm(ref).split(), norm(heard).split()
    pairs = align(r, h)
    sw = [(a, b) for a, b in pairs if a is not None and swahili.is_swahili(a)]
    return {
        "words": len(r), "errors": sum(a != b for a, b in pairs),
        "sw_words": len(sw), "sw_errors": sum(a != b for a, b in sw),
        "chars": len(" ".join(r)), "char_errors": _edits(" ".join(r), " ".join(h)),
        "pairs": pairs,
    }


def summarize(segments: list[dict], rows: list[dict]) -> list[dict]:
    """Totals per model and mode, best (fewest Swahili errors) first."""
    by_id = {s["id"]: s for s in segments}
    audio_sec = sum(s["end"] - s["start"] for s in segments)
    totals: dict[tuple[str, str], dict] = {}
    for row in rows:
        seg = by_id.get(row["id"])
        if seg is None or seg.get("ref") is None:
            continue
        t = totals.setdefault((row["model"], row["mode"]), {"model": row["model"], "mode": row["mode"], "words": 0, "errors": 0,
                                                           "sw_words": 0, "sw_errors": 0, "chars": 0, "char_errors": 0,
                                                           "secs": 0.0, "failed": 0})
        s = score(seg["ref"], row["text"])
        for k in ("words", "errors", "sw_words", "sw_errors", "chars", "char_errors"):
            t[k] += s[k]
        t["secs"] += row["secs"]
        t["failed"] += bool(row.get("error"))
    out = []
    for t in totals.values():
        t["wer"] = round(t["errors"] / t["words"], 3) if t["words"] else None
        t["sw_wer"] = round(t["sw_errors"] / t["sw_words"], 3) if t["sw_words"] else None
        t["cer"] = round(t["char_errors"] / t["chars"], 3) if t["chars"] else None
        t["secs_per_min"] = round(t["secs"] / audio_sec * 60, 2) if audio_sec else None
        out.append(t)
    return sorted(out, key=lambda t: (t["sw_wer"] if t["sw_wer"] is not None else 9, t["wer"] or 9))


# ---------- the command ----------

def cli(args) -> int:
    """`tetclipper asr bench`: build the segments here, hear them on the GPU, score here."""
    from ..spec import glossary

    segments: list[dict] = []
    for item in args.history or []:
        job, _, clip = item.partition(":")
        job_dir = Path(job) if Path(job).is_dir() else config.jobs_dir() / job
        segments += from_history(job_dir, int(clip or 0))
    for path in args.gold or []:
        segments += json.loads(Path(path).read_text(encoding="utf-8"))
    if not segments:
        _log("Nothing to test: pass --history JOB[:CLIP] and/or --gold FILE.")
        return 2
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = [m for m in models if m not in CANDIDATES] + [m for m in modes if m not in MODES]
    if unknown:
        _log(f"Unknown model or mode: {', '.join(unknown)} (models: {', '.join(CANDIDATES)}; modes: {', '.join(MODES)})")
        return 2
    hotwords, prompt = glossary.hotwords(), glossary.INITIAL_PROMPT
    _log(f"{len(segments)} segments, {sum(s['end'] - s['start'] for s in segments):.0f}s of audio; "
         f"models {', '.join(models)}; modes {', '.join(modes)}")
    with_audio = attach_audio(segments)
    if args.local:
        rows = run(with_audio, models, modes, hotwords, prompt)
    else:
        from ..cloud import client

        rows = client._fn("asr_bench").remote(with_audio, models, modes, hotwords, prompt)
    summary = summarize(segments, rows)
    out = Path(args.out)
    out.write_text(json.dumps({"segments": segments, "rows": rows, "summary": summary,
                               "labels": {k: CANDIDATES[k].label for k in models}}, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"{'model':10} {'mode':5} {'words wrong':>12} {'Swahili wrong':>14} {'letters wrong':>14} {'s/min audio':>12}")
    for t in summary:
        pct = lambda v: "-" if v is None else f"{v * 100:.0f}%"  # noqa: E731
        print(f"{t['model']:10} {t['mode']:5} {pct(t['wer']):>12} {pct(t['sw_wer']):>14} {pct(t['cer']):>14} {t['secs_per_min']:>12}")
    print(f"Saved {out}")
    return 0
