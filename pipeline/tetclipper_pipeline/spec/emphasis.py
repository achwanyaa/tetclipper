"""Which caption words get the emphasis colour: power words, numbers, and the
loudest 15% of words in the clip (per-word RMS from the events stage)."""

from __future__ import annotations

import re
from dataclasses import dataclass

EMPHASIS_RMS_QUANTILE = 0.85
_NUMERIC = re.compile(r"\d")

POWER_WORDS = {
    "insane", "crazy", "never", "secret", "worst", "best", "free", "money",
    "dead", "shocked", "literally", "truth", "million", "billion", "hate",
    "love", "wild", "unbelievable", "actually", "exposed", "huge", "zero",
}


@dataclass
class Word:
    text: str
    start: float  # relative to clip start
    end: float
    emphasized: bool = False


def mark_emphasis(words: list[Word], rms_curve, grid_sec: float, clip_start: float) -> None:
    """OR-combine: power-word/numeric baseline + per-word RMS top quantile."""
    import numpy as np

    rms = np.asarray(rms_curve, dtype=float)
    word_rms = []
    for w in words:
        a = int((clip_start + w.start) / grid_sec)
        b = max(a + 1, int((clip_start + w.end) / grid_sec))
        word_rms.append(float(np.mean(rms[a : min(b, len(rms))])) if a < len(rms) else 0.0)
    threshold = float(np.quantile(word_rms, EMPHASIS_RMS_QUANTILE)) if word_rms else 1e9
    for w, r in zip(words, word_rms):
        token = w.text.lower().strip(".,!?\"'")
        w.emphasized = bool(
            token in POWER_WORDS or _NUMERIC.search(w.text) or (r >= threshold and r > 0)
        )
