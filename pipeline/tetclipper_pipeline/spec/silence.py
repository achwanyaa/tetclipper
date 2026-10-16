"""Remove dead air: cut long pauses (and optionally um/uh fillers) from a clip.

Rules (natural and tight modes), working on a spec's words:
  * a gap shorter than MIN_GAP always stays
  * a breath is kept on each side of every cut
  * pauses near laughter/gasps/applause are comedic timing and stay
  * natural mode keeps post-sentence pauses up to SENTENCE_PAUSE
The result is ordinary spec `cuts`, so the preview, Undo and the render all
already handle it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .glossary import norm

FILLERS = {"um", "umm", "uh", "uhh", "erm", "er", "ah", "ahh", "hmm", "mm", "eh"}
REACTIONS = ("laugh", "gasp", "scream", "applause", "cheer")
EVENT_PROTECT = 2.0
MIN_CUT = 0.2


@dataclass(frozen=True)
class Mode:
    min_gap: float
    breath: float
    sentence_pause: float  # 0 = no allowance


MODES = {
    "natural": Mode(min_gap=0.5, breath=0.15, sentence_pause=1.1),
    "tight": Mode(min_gap=0.35, breath=0.08, sentence_pause=0.0),
}


def _reactions(job_dir: Path | None) -> list[tuple[float, float]]:
    if job_dir is None or not (Path(job_dir) / "events.json").exists():
        return []
    timeline = json.loads((Path(job_dir) / "events.json").read_text(encoding="utf-8"))["data"].get("timeline", [])
    return [(e["start"] - EVENT_PROTECT, e["end"] + EVENT_PROTECT) for e in timeline if e.get("type") in REACTIONS]


def find(spec: dict, job_dir: Path | None = None, mode: str = "natural", fillers: bool = False) -> dict:
    """{cuts: [...new cuts...], kept: [{start, end, reason}], filler_words: [i…], saved: seconds}."""
    m = MODES[mode]
    src = spec["source"]
    a, b = float(src["start"]), float(src["end"])
    words = spec.get("words", [])
    filler_idx = [
        i for i, w in enumerate(words)
        if fillers and not w.get("hidden") and norm(w["text"]) in FILLERS
    ]
    # Speech = every word except removable fillers (hidden words are still spoken).
    speech = [w for i, w in enumerate(words) if i not in set(filler_idx) and w["end"] > a and w["start"] < b]
    protect = _reactions(job_dir)
    existing = spec.get("cuts", [])

    def covered(x: float, y: float) -> bool:
        return any(c["start"] <= x and c["end"] >= y for c in existing)

    gaps: list[tuple[float, float, dict | None]] = []
    if speech:
        gaps.append((a, max(a, speech[0]["start"]), None))
        for prev, cur in zip(speech, speech[1:]):
            gaps.append((prev["end"], cur["start"], prev))
        gaps.append((min(b, speech[-1]["end"]), b, speech[-1]))

    cuts, kept = [], []
    for g0, g1, prev in gaps:
        gap = g1 - g0
        if gap < m.min_gap:
            continue
        if any(g0 < pe and g1 > ps for ps, pe in protect):
            kept.append({"start": round(g0, 3), "end": round(g1, 3), "reason": "comedic timing (near a reaction)"})
            continue
        sentence_end = bool(prev and prev["text"].rstrip().endswith((".", "!", "?")))
        if sentence_end and gap <= m.sentence_pause:
            kept.append({"start": round(g0, 3), "end": round(g1, 3), "reason": "natural sentence pause"})
            continue
        # no breath needed at the clip's own edges
        x = g0 if g0 <= a else g0 + m.breath
        y = g1 if g1 >= b else g1 - m.breath
        if y - x < MIN_CUT or covered(x, y):
            continue
        cuts.append({"start": round(x, 3), "end": round(y, 3)})
    saved = round(sum(c["end"] - c["start"] for c in cuts), 2)
    return {"cuts": cuts, "kept": kept, "filler_words": filler_idx, "saved": saved}


def apply(spec: dict, found: dict) -> dict:
    """The spec with the new cuts added and removed fillers hidden from captions."""
    words = [dict(w) for w in spec.get("words", [])]
    for i in found["filler_words"]:
        words[i]["hidden"] = True
    cuts = sorted([*spec.get("cuts", []), *found["cuts"]], key=lambda c: c["start"])
    return {**spec, "cuts": cuts, "words": words}
