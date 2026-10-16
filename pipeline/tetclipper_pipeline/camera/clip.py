"""Direct the smart camera over one clip range: active-speaker detection +
the director pass → a per-frame crop trajectory (see camera/director.py)."""

from __future__ import annotations

import json
from pathlib import Path

from .. import config


def _load_stage(job_dir: Path, stage: str) -> dict:
    return json.loads((job_dir / f"{stage}.json").read_text(encoding="utf-8"))["data"]


def direct(job_dir: Path, start: float, end: float, camera_mode: str | None,
           settings: config.Settings, emit=lambda f, m: None) -> dict:
    """{fps, frames, cuts, punches} for source seconds [start, end)."""
    emit(-1, "Directing the camera…")
    import numpy as np

    from ..camera import asd as asd_mod
    from ..camera import director
    from ..camera.detect import FaceDetector
    from ..models import registry, specs

    ingest = _load_stage(job_dir, "ingest")
    diarize = _load_stage(job_dir, "diarize")
    events = _load_stage(job_dir, "events")
    curves = json.loads(Path(events["curves_path"]).read_text())

    detector = FaceDetector(str(registry.ensure(specs.ULTRAFACE, lambda f, m: None)))
    model = asd_mod.AsdModel(
        str(registry.ensure(specs.LR_ASD_FRONTEND, lambda f, m: None)),
        str(registry.ensure(specs.LR_ASD_BACKEND, lambda f, m: None)),
    )
    cam_settings = config.CameraSettings(**{**settings.camera.__dict__})
    if camera_mode:
        cam_settings.speaker_change = camera_mode

    src_w, src_h = int(ingest["probe"]["width"]), int(ingest["probe"]["height"])
    analysis = asd_mod.analyze_clip(
        ingest["media_path"], start, end, detector, model, src_w, src_h
    )
    clip_turns = [t for t in diarize["turns"] if t["end"] > start and t["start"] < end]
    traj = director.build_trajectory(
        analysis, clip_turns, events["timeline"],
        np.asarray(curves["dynamics"], dtype=float), float(curves["grid_sec"]),
        start, end, src_w, src_h, cam_settings,
    )
    return {"fps": traj.fps, "frames": traj.frames, "cuts": traj.cuts, "punches": traj.punches}
