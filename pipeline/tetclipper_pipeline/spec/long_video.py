"""Full-length horizontal videos, the cheap way.

Pushing every frame of an hour through a browser costs dollars and can run into
the render timeouts. Most of a sermon is plain footage, so a landscape clip's
plain stretches get one ffmpeg encode and only the frames that show something
extra (intro, outro, transitions, effects) go through Remotion. Overlaying those
on the encode gives the same picture for a fraction of the price.

Turning on captions, the progress bar or camera moves makes every frame count as
extra, and the render falls back to Remotion for the whole video."""

from __future__ import annotations

import math

from .timeline import FPS, _round, intro_on_screen, outro_start, segments, total_frames

# Effects closer than this share one Remotion piece: a container start costs
# more than rendering half a second of frames.
MERGE_GAP_FRAMES = 15


def is_long_video(spec: dict) -> bool:
    return spec.get("format") == "landscape"


def _merged_cuts(spec: dict) -> list[dict]:
    a, b = float(spec["source"]["start"]), float(spec["source"]["end"])
    cuts = sorted(
        ({"start": max(a, min(c["start"], c["end"])), "end": min(b, max(c["start"], c["end"])), "transition": c.get("transition")}
         for c in spec.get("cuts", [])),
        key=lambda c: c["start"],
    )
    merged: list[dict] = []
    for c in cuts:
        if c["end"] <= c["start"]:
            continue
        if merged and c["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], c["end"])
            merged[-1]["transition"] = merged[-1]["transition"] or c["transition"]
        else:
            merged.append(c)
    return merged


def cut_transitions(spec: dict, fps: int = FPS) -> list[tuple[int, int]]:
    """(first frame, frames) of each transition across a cut, exactly as
    buildTimeline() in studio/composition/src/timeline.ts."""
    a, b = float(spec["source"]["start"]), float(spec["source"]["end"])
    pieces: list[tuple[int, dict | None]] = []  # (frames, transition into this piece)
    cursor, entering = a, None

    def push(x: float, y: float) -> None:
        nonlocal entering
        frames = _round((y - x) * fps)
        if frames < 1:
            return
        pieces.append((frames, entering if pieces else None))
        entering = None

    for c in _merged_cuts(spec):
        push(cursor, c["start"])
        cursor = c["end"]
        entering = entering or c["transition"]
    push(cursor, b)

    frame = segments(spec, fps)[0]
    out: list[tuple[int, int]] = []
    previous = 0
    for frames, transition in pieces:
        if previous and transition:
            half = min(_round(float(transition.get("duration", 0.5)) * fps), previous, frames) // 2
            if half >= 1:
                out.append((frame - half, half * 2))
        frame += frames
        previous = frames
    return out


def _effect_ranges(spec: dict, fps: int) -> list[tuple[int, int]]:
    video_from, segs = segments(spec, fps)
    out: list[tuple[int, int]] = []
    for e in spec.get("effects", []):
        at, duration = float(e["at"]), float(e["duration"])
        if e.get("type") == "zoom-through":
            # Centred on an output frame: it usually straddles a cut.
            frame, centre = video_from, None
            for start, n in segs:
                if centre is None and at < start + n / fps:
                    centre = frame + _round(max(0.0, at - start) * fps)
                frame += n
            if centre is not None:
                half = max(2, math.ceil(duration * fps / 2))
                out.append((centre - half - 1, centre + half + 1))
            continue
        frame = video_from
        for start, n in segs:
            lo, hi = max(at, start), min(at + duration, start + n / fps)
            if hi > lo:
                out.append((frame + math.floor((lo - start) * fps) - 1, frame + math.ceil((hi - start) * fps) + 1))
            frame += n
    return out


def _needs_every_frame(spec: dict) -> bool:
    captions = spec.get("captions") or {}
    if captions.get("enabled", True) and any(not w.get("hidden") and str(w.get("text", "")).strip() for w in spec.get("words", [])):
        return True
    if (spec.get("progressBar") or {}).get("enabled"):
        return True
    return bool((spec.get("crop") or {}).get("keyframes"))


def remotion_ranges(spec: dict, fps: int = FPS) -> list[tuple[int, int]]:
    """Output frames (first, last inclusive) that need Remotion, merged and in order."""
    total = total_frames(spec, fps)
    if _needs_every_frame(spec):
        return [(0, total - 1)]
    ranges = _effect_ranges(spec, fps)
    ranges += [(first, first + n - 1) for first, n in cut_transitions(spec, fps)]
    if spec.get("intro"):
        ranges.append((0, intro_on_screen(spec, fps) - 1))
    if spec.get("outro"):
        ranges.append((outro_start(spec, fps), total - 1))
    merged: list[list[int]] = []
    for a, b in sorted((max(0, a), min(total - 1, b)) for a, b in ranges):
        if b < a:
            continue
        if merged and a <= merged[-1][1] + MERGE_GAP_FRAMES:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def base_filter(spec: dict, width: int, height: int, fps: int = FPS) -> str:
    """Source video → the plain picture of every output frame: kept frames only,
    framed like the composition (cover, centred), black before and after."""
    video_from, segs = segments(spec, fps)
    keep = "+".join(f"between(n,{_round(start * fps)},{_round(start * fps) + n - 1})" for start, n in segs) or "0"
    source = spec["source"]
    frame = "" if (source.get("width"), source.get("height")) == (width, height) else (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},")
    return (
        f"fps={fps}:start_time=0,select='{keep}',setpts=N/{fps}/TB,{frame}setsar=1,format=yuv420p,"
        f"tpad=start={video_from}:stop={total_frames(spec, fps)}:color=black"
    )


def overlay_filter(ranges: list[tuple[int, int]], fps: int = FPS) -> tuple[str, str]:
    """(timing for the joined Remotion frames, overlay `enable`): each frame of the
    joined file lands on its own output frame, and only there covers the base."""
    shift = f"N+{ranges[0][0]}"
    done = 0
    for (a, b), (next_a, _) in zip(ranges, ranges[1:]):
        done += b - a + 1
        shift += f"+gte(N,{done})*{next_a - b - 1}"
    # By time, half a frame wide each side: on the render's ffmpeg (Debian's 5.1) `n` here
    # counts differently, and only the first frame of each range would show.
    enable = "+".join(f"between(t,{(a - 0.5) / fps:.5f},{(b + 0.5) / fps:.5f})" for a, b in ranges)
    return f"setpts='({shift})/{fps}/TB',format=yuv420p", enable
