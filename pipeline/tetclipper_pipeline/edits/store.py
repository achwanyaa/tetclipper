"""Per-clip settings recorded when a clip is created, in <job_dir>/clip_edits.json:
bounds, caption style, camera mode and caption word fixes. spec/build.py reads
them once to build the clip's Studio spec; after that the spec is the truth.
Defaults for a clip with no entry come from score.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


def word_key(start: float) -> str:
    """Stable id for a transcript word: its source start time."""
    return f"{float(start):.3f}"


@dataclass
class ClipEdit:
    start: float
    end: float
    caption_preset: str | None = None
    camera_mode: str | None = None
    # Caption text fixes: word_key(start) -> replacement ("" hides the word).
    word_edits: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_json(cls, data: dict) -> "ClipEdit":
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            caption_preset=data.get("caption_preset"),
            camera_mode=data.get("camera_mode"),
            word_edits={str(k): str(v) for k, v in (data.get("word_edits") or {}).items()},
        )


def path_for(job_dir: Path) -> Path:
    return Path(job_dir) / "clip_edits.json"


def load(job_dir: Path) -> dict[str, ClipEdit]:
    p = path_for(job_dir)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: ClipEdit.from_json(v) for k, v in raw.items()}


def save(job_dir: Path, edits: dict[str, ClipEdit]) -> None:
    tmp = path_for(job_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps({k: e.to_json() for k, e in edits.items()}, indent=1), encoding="utf-8")
    tmp.replace(path_for(job_dir))


def edit_for_clip(job_dir: Path, clip_idx: int, score_clip: dict) -> ClipEdit:
    """The stored settings, or defaults from the score entry."""
    edits = load(job_dir)
    if str(clip_idx) in edits:
        return edits[str(clip_idx)]
    return ClipEdit(start=float(score_clip["start"]), end=float(score_clip["end"]))
