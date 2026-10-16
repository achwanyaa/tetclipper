"""Manual clips: the user picks an exact source range instead of (or as well
as) the auto-found moments. The range becomes one more entry in score.json
(flagged ``manual``); spec/build.py then directs the camera for it and builds
its Studio spec.

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

MIN_SEC = 3.0
# Shorts/Reels cap at 3 min, TikTok at 10; longer only costs render time.
MAX_SEC = 600.0


def _stage(job_dir: Path, name: str) -> dict | None:
    path = job_dir / f"{name}.json"
    return json.loads(path.read_text())["data"] if path.exists() else None


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
    """Append the range to score.json as a clip (its spec is built next).
    Returns {"clip_index", "start", "end"}."""
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

    edits = store.load(job_dir)
    edit = store.edit_for_clip(job_dir, clip_idx, score["clips"][clip_idx])
    edit.caption_preset = caption_preset or edit.caption_preset
    edit.camera_mode = camera_mode or edit.camera_mode
    edits[str(clip_idx)] = edit
    store.save(job_dir, edits)

    emit(-1, f"Clip {_fmt(start)}–{_fmt(end)} added")
    return {"clip_index": clip_idx, "start": start, "end": end}
