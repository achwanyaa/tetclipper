"""Output timeline maths, matching studio/composition/src/timeline.ts exactly
(frame-rounded segments), so the Python render path and the Remotion preview
agree on every frame."""

from __future__ import annotations

FPS = 30


def _round(x: float) -> int:
    return int(x + 0.5)  # JS Math.round for the non-negative values used here


def segments(spec: dict, fps: int = FPS) -> tuple[int, list[tuple[float, int]]]:
    """(intro frames, [(source start, frames)]) exactly as buildTimeline() in
    studio/composition/src/timeline.ts: the source range minus merged cuts."""
    src = spec["source"]
    a, b = float(src["start"]), float(src["end"])
    intro = spec.get("intro")
    intro_frames = _round(float(intro.get("duration", 2)) * fps) if intro else 0
    cuts = sorted(
        (max(a, min(c["start"], c["end"])), min(b, max(c["start"], c["end"])))
        for c in spec.get("cuts", [])
    )
    merged: list[list[float]] = []
    for c0, c1 in cuts:
        if c1 <= c0:
            continue
        if merged and c0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], c1)
        else:
            merged.append([c0, c1])
    out: list[tuple[float, int]] = []
    cursor = a
    for c0, c1 in [*merged, [b, b]]:
        n = _round((c0 - cursor) * fps)
        if n >= 1:
            out.append((cursor, n))
        cursor = c1
    return intro_frames, out


def total_frames(spec: dict, fps: int = FPS) -> int:
    """Output length in frames: intro + every kept segment."""
    intro, segs = segments(spec, fps)
    return max(1, intro + sum(n for _, n in segs))



def source_time_at(intro_frames: int, segs: list[tuple[float, int]], frame: int, fps: int = FPS) -> float | None:
    """Source seconds shown at an output frame (None during the intro)."""
    if frame < intro_frames:
        return None
    start = intro_frames
    for seg_start, n in segs:
        if frame < start + n:
            return seg_start + (frame - start) / fps
        start += n
    return segs[-1][0] + segs[-1][1] / fps if segs else None
