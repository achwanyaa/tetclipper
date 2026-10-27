"""Paths and settings.

Everything lives under TETCLIPPER_HOME (default ~/.tetclipper):

    ~/.tetclipper/
      db.sqlite3          job + stage bookkeeping
      bin/                managed binaries (yt-dlp)
      models/             downloaded model weights
      jobs/<job_id>/      per-job artifacts (media, audio, stage checkpoints)
      secrets.json        keys (0600): own Gemini key, Pexels, Telegram, …

The desktop shell and the CLI both use the same resolution (TETCLIPPER_HOME,
else ~/.tetclipper), so secrets.json written by onboarding is what the
pipeline reads. Artifacts on disk are the source of truth — the DB only records
what should exist so a stage can decide whether to skip itself on resume.
"""

from __future__ import annotations

import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

# The hosted app gives each signed-in user a private workspace, TETCLIPPER_HOME/
# users/<id>/, for their jobs, uploads and job database. Models, binaries,
# secrets, the music library and the word list stay shared at TETCLIPPER_HOME.
# The web server sets WORKSPACE per request; a CLI it spawns gets
# TETCLIPPER_WORKSPACE. Unset (desktop, CLI), the workspace is the home itself.
WORKSPACE: ContextVar[Path | None] = ContextVar("tetclipper_workspace", default=None)


def home_dir() -> Path:
    return Path(os.environ.get("TETCLIPPER_HOME", str(Path.home() / ".tetclipper")))


def workspace_dir() -> Path:
    ws = WORKSPACE.get() or os.environ.get("TETCLIPPER_WORKSPACE")
    return Path(ws) if ws else home_dir()


def jobs_dir() -> Path:
    return workspace_dir() / "jobs"


def bin_dir() -> Path:
    return home_dir() / "bin"


def models_dir() -> Path:
    return home_dir() / "models"


def db_path() -> Path:
    return workspace_dir() / "db.sqlite3"


def compute_device() -> str:
    """Where the torch/ctranslate2 models run: TETCLIPPER_DEVICE if set,
    else cuda when a GPU is visible (the hosted worker), else cpu (laptops;
    ctranslate2 has no MPS backend)."""
    forced = os.environ.get("TETCLIPPER_DEVICE")
    if forced:
        return forced
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 — torch missing or broken: stay on cpu
        return "cpu"


def ensure_home() -> Path:
    root = home_dir()
    for d in (root, workspace_dir(), jobs_dir(), bin_dir(), models_dir()):
        d.mkdir(parents=True, exist_ok=True)
    return root


# Hard per-attempt network timeouts (seconds). A blackholed connection must
# never freeze the pipeline — every subprocess/network call takes one of these.
HTTP_TIMEOUT = 60.0
SUBPROCESS_INACTIVITY_TIMEOUT = 120.0  # kill if no output for this long
PROBE_TIMEOUT = 60.0

# Ingest
MAX_HEIGHT = 1080
AUDIO_SR = 16_000  # analysis sample rate; every M1 model consumes this wav


@dataclass
class CameraSettings:
    """User-facing camera preset knobs (locked decision #7: exposed options)."""

    # 'cut' = hard cut on speaker change (default), 'pan' = eased pan between
    # speakers, 'locked' = static crop on the dominant face.
    speaker_change: str = "cut"
    pan_duration_s: float = 0.6
    deadzone_frac: float = 0.05  # ignore drift below this fraction of width
    punch_in: bool = True
    punch_in_sensitivity: float = 1.0  # scales event/energy trigger thresholds
    zoom_lock_per_scene: bool = True


@dataclass
class Settings:
    """Per-job settings snapshot. Serialized into the job dir at creation so a
    resumed job never silently picks up changed defaults."""

    camera: CameraSettings = field(default_factory=CameraSettings)
    lufs_target: float = -14.0  # decision #8: configurable per destination
    true_peak_db: float = -1.0
    # 'claude' (Claude Code handoff, default) | 'gemini' (your own key) | 'ollama' (local)
    llm_mode: str = "claude"
    caption_preset: str = "classic"
    # jrgillick laughter specialist: 10 ms precision but ~300k CPU forward
    # passes on an hour-plus source. OFF by default — PANNs' AudioSet
    # laughter classes cover the bus at 320 ms resolution for a fraction of
    # the compute; flip on for the two-detector agreement boost.
    laughter_specialist: bool = False
    # Range jobs: [start, end] source seconds to fetch instead of the whole
    # video (yt-dlp --download-sections, or a trim of a local file).
    section: list[float] | None = None
    # Speech language for transcription ("en", "sw", …); None = auto-detect
    # from the first 30 s, which misfires on short slices of mixed speech.
    language: str | None = None

    def to_json(self) -> dict:
        return {
            "camera": self.camera.__dict__.copy(),
            "lufs_target": self.lufs_target,
            "true_peak_db": self.true_peak_db,
            "llm_mode": self.llm_mode,
            "caption_preset": self.caption_preset,
            "laughter_specialist": self.laughter_specialist,
            "section": self.section,
            "language": self.language,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Settings":
        cam = CameraSettings(**data.get("camera", {}))
        return cls(
            camera=cam,
            lufs_target=data.get("lufs_target", -14.0),
            true_peak_db=data.get("true_peak_db", -1.0),
            llm_mode=data.get("llm_mode", "claude"),
            caption_preset=data.get("caption_preset", "classic"),
            laughter_specialist=data.get("laughter_specialist", False),
            section=data.get("section"),
            language=data.get("language"),
        )
