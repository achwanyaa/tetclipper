"""Manual clips: the user picks an exact source range instead of (or as well
as) the auto-found moments. The range becomes one more entry in score.json
(flagged ``manual``), then goes through the same per-clip render path as an
edited clip: speaker-tracked camera direction for the new bounds, captions
with loud-word emphasis, event tags.

Needs ingest + diarize + events (the transcript, speakers and audio signals
for the whole video). Auto-scoring is optional: on a job that never scored,
the first manual clip creates score.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .. import config
from ..jobs import queue
from ..scoring.stage import ScoreStage, _events_in, _window_pct
from . import store
from .render_clip import render_clip_edit

MIN_SEC = 3.0
# Shorts/Reels cap at 3 min, TikTok at 10; longer only costs render time.
MAX_SEC = 600.0


def _stage(job_dir: Path, name: str) -> dict | None:
    path = job_dir / f"{name}.json"
    return json.loads(path.read_text())["data"] if path.exists() else None


def transcript(job_dir: Path) -> dict:
    """Whole-video words + speaker for the range picker."""
    ingest = _stage(job_dir, "ingest")
    diarize = _stage(job_dir, "diarize")
    if not (ingest and diarize):
        raise ValueError("This job has no transcript yet. Run it until TRANSCRIBE and SPEAKERS finish.")
    # Prefer the job dir's own copy: a job moved between homes still plays.
    local = job_dir / "media.mp4"
    return {
        "media_path": str(local) if local.exists() else ingest["media_path"],
        "duration": float(ingest["probe"]["duration_sec"]),
        "title": ingest.get("title"),
        "segments": [
            {
                "speaker": seg.get("speaker", 0),
                "words": [[w["word"], round(w["start"], 2), round(w["end"], 2)] for w in seg.get("words", []) if "start" in w],
            }
            for seg in diarize["segments"]
        ],
    }


def transcript_text(job_dir: Path, start: float | None = None, end: float | None = None,
                    find: str | None = None) -> str:
    """Plain-text transcript for a reader (the chat brain): one line per
    sentence as "[m:ss.s-m:ss.s] S0: text", optionally limited to a window or
    to sentences containing `find` (case-insensitive)."""
    data = transcript(job_dir)
    lines = []
    needle = find.lower() if find else None
    for seg in data["segments"]:
        words = seg["words"]
        if not words:
            continue
        a, b = words[0][1], words[-1][2]
        if start is not None and b < start:
            continue
        if end is not None and a > end:
            continue
        text = " ".join(w[0] for w in words)
        if needle and needle not in text.lower():
            continue
        lines.append(f"[{_fmt(a)}-{_fmt(b)}] S{seg['speaker']}: {text}")
    head = f"{data.get('title') or job_dir.name} - {_fmt(data['duration'])} long"
    return head + "\n" + ("\n".join(lines) if lines else "(no matching lines)")


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def manual_clip_entry(job_dir: Path, start: float, end: float) -> dict:
    """A score.json clip for a hand-picked range. No judge ran, so no
    subscores: the card says so instead of inventing a number."""
    diarize = _stage(job_dir, "diarize") or {"segments": []}
    events = _stage(job_dir, "events") or {"timeline": []}
    words = [
        w["word"] for seg in diarize["segments"] for w in seg.get("words", [])
        if "start" in w and start <= w["start"] < end
    ]
    arousal_pct = 0.0
    if events.get("curves_path") and Path(events["curves_path"]).exists():
        curves = json.loads(Path(events["curves_path"]).read_text())
        arousal = np.asarray(curves.get("arousal", []), dtype=float)
        if arousal.size:
            arousal_pct = _window_pct(arousal, float(curves.get("arousal_grid_sec", 0.5)), start, end)
    window_events = _events_in(events["timeline"], start, end)
    preview = " ".join(words[:14]) + ("…" if len(words) > 14 else "")
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "manual": True,
        "score": 0,
        "best_platform": "reels",
        "platform_scores": {},
        "subscores": {},
        "adjustments": [],
        "signals_fired": sorted({e["type"] for e in window_events if e["type"] != "pause"}),
        "signals_missing": ["judge (manual pick)"],
        "confidence": "manual",
        "summary": f"Manual clip {_fmt(start)}–{_fmt(end)}: {preview}",
        "arousal_pct": round(arousal_pct, 3),
        "heatmap_pct": None,
        "curve_score": 0.0,
        "channel_scores": {},
        "music": None,
    }


def add_range(
    job: queue.Job,
    start: float,
    end: float,
    emit,
    caption_preset: str | None = None,
    camera_mode: str | None = None,
) -> dict:
    """Append the range as a clip and render it. Returns the render entry."""
    job_dir = Path(job.dir)
    missing = [s for s in ("ingest", "diarize", "events") if not (job_dir / f"{s}.json").exists()]
    if missing:
        raise ValueError(f"Finish {', '.join(missing)} first: manual clips need the transcript and audio signals.")
    duration = float(_stage(job_dir, "ingest")["probe"]["duration_sec"])
    start, end = max(0.0, float(start)), min(duration, float(end))
    if not MIN_SEC <= end - start <= MAX_SEC:
        raise ValueError(f"A clip must be {MIN_SEC:.0f}–{MAX_SEC:.0f} s long (got {end - start:.1f} s).")

    settings = config.Settings.from_json(json.loads(job.settings_json))
    score = _stage(job_dir, "score") or {
        "llm_mode": "manual",
        "model": "none",
        "clips": [],
        "scored_count": 0,
        "t2_ran": False,
        "scoring_config_version": None,
        "scoring_constants": {},
    }
    score["clips"].append(manual_clip_entry(job_dir, start, end))
    clip_idx = len(score["clips"]) - 1
    queue.write_checkpoint(job, "score", ScoreStage.schema_version, score)

    # render_clip_edit keeps render.json in sync only if it exists.
    if not (job_dir / "render.json").exists():
        queue.write_checkpoint(job, "render", 1, {
            "outputs": [], "emoji_ok": False, "caption_preset": settings.caption_preset,
        })

    edits = store.load(job_dir)
    edit = store.edit_for_clip(job_dir, clip_idx, score["clips"][clip_idx])
    edit.caption_preset = caption_preset or edit.caption_preset
    edit.camera_mode = camera_mode or edit.camera_mode
    edits[str(clip_idx)] = edit
    store.save(job_dir, edits)

    emit(-1, f"Cutting {_fmt(start)}–{_fmt(end)}…")
    return render_clip_edit(job_dir, clip_idx, emit)
