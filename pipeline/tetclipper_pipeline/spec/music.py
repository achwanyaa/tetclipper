"""Music bed gains per output frame — the same rules as
studio/composition/src/music.ts, so the cloud mix matches the preview."""

from __future__ import annotations

from .timeline import FPS, intro_on_screen, outro_start, segments, source_time_at, total_frames

MERGE_GAP = 0.35
PAD = 0.08
RAMP = 0.15


def speech_spans(words: list[dict]) -> list[tuple[float, float]]:
    spans: list[list[float]] = []
    for w in sorted(words, key=lambda w: w["start"]):
        if spans and w["start"] - spans[-1][1] < MERGE_GAP:
            spans[-1][1] = max(spans[-1][1], w["end"])
        else:
            spans.append([w["start"], w["end"]])
    return [(a - PAD, b + PAD) for a, b in spans]


def music_settings(spec: dict) -> dict | None:
    m = spec.get("music")
    if not m:
        return None
    return {"volume": 0.25, "duck": 0.35, "offset": 0.0, "fadeIn": 1.0, "fadeOut": 1.5, "loop": True, "end": None, **m}


def music_range(m: dict) -> tuple[float, float | None]:
    """The track range in use: (start, end), end None = the track's end."""
    start, end = float(m["offset"]), m.get("end")
    return start, float(end) if end is not None and float(end) > start else None


def _has_sound(item: dict | None) -> bool:
    return bool(item) and item.get("kind") == "video" and float(item.get("volume", 1)) > 0


def frame_gains(spec: dict, fps: int = FPS) -> list[float]:
    n = total_frames(spec, fps)
    m = music_settings(spec)
    if m is None:
        return [0.0] * n
    intro, segs = segments(spec, fps)
    spans = speech_spans(spec.get("words", []))
    step = (1 - m["duck"]) / max(1.0, RAMP * fps)
    start, end = music_range(m)
    last = min(n, int((end - start) * fps + 0.5)) if not m["loop"] and end is not None else n
    has_outro = bool(spec.get("outro"))
    intro_until = intro_on_screen(spec, fps) if _has_sound(spec.get("intro")) else 0
    outro_from = outro_start(spec, fps) if _has_sound(spec.get("outro")) else n
    gains: list[float] = []
    duck = 1.0
    for f in range(n):
        t = source_time_at(intro, segs, f, fps, has_outro)
        speaking = (t is not None and any(a <= t <= b for a, b in spans)) or f < intro_until or f >= outro_from
        target = m["duck"] if speaking else 1.0
        duck += max(-step, min(step, target - duck))
        fade_in = f / (m["fadeIn"] * fps) if m["fadeIn"] > 0 else 1.0
        fade_out = (last - 1 - f) / (m["fadeOut"] * fps) if m["fadeOut"] > 0 else (1.0 if f < last else 0.0)
        gains.append(m["volume"] * duck * max(0.0, min(1.0, fade_in, fade_out)))
    return gains
