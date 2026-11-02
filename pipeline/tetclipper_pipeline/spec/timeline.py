"""Output timeline maths, matching studio/composition/src/timeline.ts exactly
(frame-rounded segments), so the Python render path and the Remotion preview
agree on every frame."""

from __future__ import annotations

FPS = 30


def _round(x: float) -> int:
    return int(x + 0.5)  # JS Math.round for the non-negative values used here


def _bookend_frames(item: dict | None, video_frames: int, fps: int) -> tuple[int, int]:
    """(frames on screen, frames overlapping the video) for an intro or outro."""
    if not item:
        return 0, 0
    on_screen = _round(float(item.get("duration", 2)) * fps)
    transition = item.get("transition")
    wanted = _round(float(transition.get("duration", 0.5)) * fps) if transition else 0
    return on_screen, max(0, min(wanted, on_screen - 1, video_frames))


def segments(spec: dict, fps: int = FPS) -> tuple[int, list[tuple[float, int]]]:
    """(frame the video starts at, [(source start, frames)]) exactly as
    buildTimeline() in studio/composition/src/timeline.ts: the source range minus
    merged cuts, after the intro less any overlap with its transition."""
    src = spec["source"]
    a, b = float(src["start"]), float(src["end"])
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
    on_screen, overlap = _bookend_frames(spec.get("intro"), sum(n for _, n in out), fps)
    return on_screen - overlap, out


def outro_start(spec: dict, fps: int = FPS) -> int:
    """The outro's first frame (the output's end when there is no outro)."""
    intro, segs = segments(spec, fps)
    video = sum(n for _, n in segs)
    return intro + video - _bookend_frames(spec.get("outro"), video, fps)[1]


def total_frames(spec: dict, fps: int = FPS) -> int:
    """Output length in frames: intro + every kept segment + outro."""
    _, segs = segments(spec, fps)
    on_screen = _bookend_frames(spec.get("outro"), sum(n for _, n in segs), fps)[0]
    return max(1, outro_start(spec, fps) + on_screen)


def intro_on_screen(spec: dict, fps: int = FPS) -> int:
    return _bookend_frames(spec.get("intro"), sum(n for _, n in segments(spec, fps)[1]), fps)[0]



def source_time_at(intro_frames: int, segs: list[tuple[float, int]], frame: int, fps: int = FPS,
                   has_outro: bool = False) -> float | None:
    """Source seconds shown at an output frame (None during the intro, or once
    only the outro is left)."""
    if frame < intro_frames or (has_outro and frame >= intro_frames + sum(n for _, n in segs)):
        return None
    start = intro_frames
    for seg_start, n in segs:
        if frame < start + n:
            return seg_start + (frame - start) / fps
        start += n
    return segs[-1][0] + segs[-1][1] / fps if segs else None
