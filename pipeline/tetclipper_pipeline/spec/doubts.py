"""Doubtful caption spans + a Swahili second opinion.

Claude can read Swahili/Sheng but can't hear the audio, and alignment scores
don't catch mishearings (the English aligner happily times the English words
it's given: "able to show me" scored 0.64–0.89). The reliable tell is timing:
when Whisper writes too little text for the audio, one word swallows the rest
("me" lasting 1.38 s). Those spans are re-heard with Whisper forced to
Swahili; the reading is kept as `alt` only when it differs. The editor shows
the spans for the user to check by ear, and Claude chooses between readings
using context.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .glossary import norm

LONG_WORD_SEC = 0.7  # a word this long…
PER_CHAR_SEC = 0.12  # …and much longer than its letters justify
SLACK_SEC = 0.45
LOW_SCORE = 0.3
LOOK_BACK = 3  # misheard words sit before the swallowing word
JOIN_GAP = 0.25
PAD_SEC = 0.3

_ALNUM = re.compile(r"\w", re.UNICODE)


def _too_long(w: dict) -> bool:
    dur = w["end"] - w["start"]
    chars = len(_ALNUM.findall(w["text"])) or 1
    return dur > LONG_WORD_SEC and dur > PER_CHAR_SEC * chars + SLACK_SEC


def detect(words: list[dict], scores: dict[int, float] | None = None) -> list[dict]:
    """[{from, to, reason}] over visible words. `scores` maps word index →
    alignment score (when known)."""
    scores = scores or {}
    spans: list[dict] = []
    for i, w in enumerate(words):
        if w.get("hidden"):
            continue
        reason = None
        if _too_long(w):
            reason = "too long for the word (something may be missing)"
        elif scores.get(i, 1.0) < LOW_SCORE and len(_ALNUM.findall(w["text"])) > 2:
            reason = "unclear audio"
        if not reason:
            continue
        a = i
        for _ in range(LOOK_BACK):
            p = a - 1
            if p < 0 or words[p].get("hidden"):
                break
            if words[p]["text"].rstrip()[-1:] in ".,!?;:" or words[a]["start"] - words[p]["end"] > JOIN_GAP:
                break
            a = p
        if spans and a <= spans[-1]["to"] + 1:
            spans[-1]["to"] = i
        else:
            spans.append({"from": a, "to": i, "reason": reason})
    return spans


def tidy(text: str) -> str:
    """Drop Whisper's short-clip repetition tails ("ebu tusome, hapa, hapa, hapa"
    → "ebu tusome, hapa"): collapse any 1–3 word phrase repeated back to back."""
    tokens = text.split()
    changed = True
    while changed:
        changed = False
        for n in (3, 2, 1):
            i = 0
            while i + 2 * n <= len(tokens):
                if [norm(t) for t in tokens[i : i + n]] == [norm(t) for t in tokens[i + n : i + 2 * n]]:
                    del tokens[i + n : i + 2 * n]
                    changed = True
                else:
                    i += 1
    return " ".join(tokens).rstrip(",;: ")


def is_alternative(current: str, heard: str) -> bool:
    """A different reading, not the same words plus a few neighbours caught by
    the padding ("you can" → "you can speak to")."""
    cur, alt = norm(current), norm(heard)
    if not alt or alt == cur:
        return False
    if cur and cur in alt and len(alt.split()) - len(cur.split()) <= 3:
        return False
    return True


def load_model(model_name: str):
    """A faster-whisper model on this machine's device: a size name, a Hugging
    Face repo, or a converted folder (asr/bench.py)."""
    from faster_whisper import WhisperModel

    from .. import config
    from ..asr.stage import _point_caches_at_home

    _point_caches_at_home()  # reuse the speech model ASR already downloaded
    device = config.compute_device()
    return WhisperModel(model_name, device=device, compute_type="float16" if device == "cuda" else "int8")


def hear(model, clip, language: str | None, hotwords: str = "", prompt: str | None = None) -> str:
    """What `model` hears in `clip` (16 kHz float32 samples), tuned for short
    spans: no carry-over between windows, repetition damped, and at most ~6
    tokens a second (~3 words a second is already fast speech). language
    None lets the model pick."""
    seconds = len(clip) / 16000
    segments, _ = model.transcribe(
        clip, language=language, beam_size=5, vad_filter=False, condition_on_previous_text=False,
        hotwords=hotwords or None, initial_prompt=prompt, temperature=0.0, no_repeat_ngram_size=3,
        repetition_penalty=1.15, max_new_tokens=min(int(seconds * 6) + 6, 200),  # per 30 s window
    )
    return tidy(" ".join(s.text.strip() for s in segments).strip())


def second_opinion(audio_path: Path, words: list[dict], spans: list[dict], hotwords: str = "",
                   model_name: str | None = None) -> list[dict]:
    """Re-hear each span with Whisper forced to Swahili; add `alt` when it differs."""
    if not spans:
        return spans
    from ..asr.stage import load_audio

    model = load_model(model_name or os.environ.get("TETCLIPPER_ALT_MODEL", "large-v3-turbo"))
    language = os.environ.get("TETCLIPPER_ALT_LANG", "sw")
    audio = load_audio(Path(audio_path))
    rate = 16000
    out = []
    for span in spans:
        a = max(0.0, words[span["from"]]["start"] - PAD_SEC)
        b = words[span["to"]]["end"] + PAD_SEC
        heard = hear(model, audio[int(a * rate) : int(b * rate)], language, hotwords)
        current = " ".join(w["text"] for w in words[span["from"] : span["to"] + 1] if not w.get("hidden"))
        item = dict(span)
        if heard and is_alternative(current, heard):
            item["alt"] = heard
        out.append(item)
    return out


def enabled() -> bool:
    return os.environ.get("TETCLIPPER_SECOND_OPINION", "1") != "0"
