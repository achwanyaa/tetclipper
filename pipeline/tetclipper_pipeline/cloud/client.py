"""This PC's side of Studio-on-Modal: push job files to the volume, run the
deployed function, pull the results back with paths rewritten to this machine.

Needs the `cloud` dependency group (modal) and a logged-in Modal CLI
(~/.modal.toml), plus `modal deploy pipeline/modal_app.py`.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .. import config
from . import APP_NAME, REMOTE_HOME, VOLUME_NAME

Emit = Callable[[str, float, str], None]
# Never sent back down: the PC has the media already; renders come separately.
PULL_SKIP = {"media.mp4", "audio16k.wav", "diar_embeddings.npy"}


def available() -> bool:
    """Cloud mode is usable: SDK installed, CLI logged in, not switched off."""
    if os.environ.get("TETCLIPPER_CLOUD", "1") == "0":
        return False
    try:
        import modal  # noqa: F401
    except ImportError:
        return False
    return (Path.home() / ".modal.toml").exists() or bool(os.environ.get("MODAL_TOKEN_ID"))


def _volume():
    import modal

    return modal.Volume.from_name(VOLUME_NAME)


def _fn(name: str):
    import modal

    return modal.Function.from_name(APP_NAME, name)


def _remote_rel(job_id: str, rel: str) -> str:
    return f"/jobs/{job_id}/{rel}"


def _remap(value: Any, src_prefix: str, to_path: Callable[[str], str]) -> Any:
    """Rewrite every string that starts with src_prefix (an absolute home)."""
    if isinstance(value, str):
        if value.startswith(src_prefix):
            return to_path(value[len(src_prefix):].lstrip("/\\"))
        return value
    if isinstance(value, list):
        return [_remap(v, src_prefix, to_path) for v in value]
    if isinstance(value, dict):
        return {k: _remap(v, src_prefix, to_path) for k, v in value.items()}
    return value


def to_remote(value: Any) -> Any:
    local = str(config.home_dir())
    return _remap(value, local, lambda rest: f"{REMOTE_HOME}/" + rest.replace("\\", "/"))


def to_local(value: Any) -> Any:
    home = config.home_dir()
    return _remap(value, REMOTE_HOME + "/", lambda rest: str(home.joinpath(*PurePosixPath(rest).parts)))


def push_files(job_dir: Path, rels: list[str], emit: Emit, stage: str = "upload") -> None:
    """Upload job files (relative paths) to the volume; JSON paths rewritten."""
    vol = _volume()
    job_id = job_dir.name
    staged: list[tuple[Path, str]] = []
    tmp_dir = job_dir / ".cloud"
    tmp_dir.mkdir(exist_ok=True)
    for rel in rels:
        src = job_dir / rel
        if not src.exists():
            continue
        if src.suffix == ".json":
            fixed = tmp_dir / rel.replace("/", "__")
            fixed.write_text(json.dumps(to_remote(json.loads(src.read_text(encoding="utf-8")))), encoding="utf-8")
            src = fixed
        staged.append((src, _remote_rel(job_id, rel)))
    total = sum(p.stat().st_size for p, _ in staged) or 1
    emit(stage, 0.0, f"Uploading {total // 1_000_000} MB to the cloud…")
    with vol.batch_upload(force=True) as batch:
        for path, remote in staged:
            batch.put_file(str(path), remote)
    emit(stage, 1.0, "Uploaded")


def pull_job(job_dir: Path, emit: Emit, only: str | None = None) -> int:
    """Download the job's files from the volume (except media), rewriting paths."""
    vol = _volume()
    job_id = job_dir.name
    prefix = _remote_rel(job_id, only or "").rstrip("/")
    entries = [e for e in vol.listdir(prefix, recursive=True) if e.type.name == "FILE"]
    n = 0
    for e in entries:
        rel = e.path.split(f"jobs/{job_id}/", 1)[-1]
        if rel in PULL_SKIP or rel.startswith((".cloud/", "t2frames/")) or rel.endswith(".part.mp4"):
            continue
        dest = job_dir.joinpath(*PurePosixPath(rel).parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest.with_name(dest.name + ".part"), "wb") as out:
            vol.read_file_into_fileobj(e.path, out)
        tmp = dest.with_name(dest.name + ".part")
        if dest.suffix == ".json":
            try:
                data = json.loads(tmp.read_text(encoding="utf-8"))
                tmp.write_text(json.dumps(to_local(data), indent=1), encoding="utf-8")
            except ValueError:
                pass
        tmp.replace(dest)
        n += 1
    emit("download", 1.0, f"Pulled {n} files")
    return n


def _relay(gen, emit: Emit) -> dict:
    result: dict = {}
    for ev in gen:
        if ev.get("event") == "progress":
            emit(ev.get("stage", "cloud"), float(ev.get("fraction", -1)), ev.get("message", ""))
        elif ev.get("event") == "result":
            result = ev
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "the cloud job failed")
    return result


def analyze(job, start: float | None, end: float | None, captions: str | None, emit: Emit,
            stages: list[str] | None = None) -> dict:
    """Job whose ingest ran here → GPU analysis on Modal → results pulled back.
    Range mode builds the clip spec too; find mode runs just `stages`."""
    job_dir = Path(job.dir)
    push_files(job_dir, ["ingest.json", "media.mp4", "audio16k.wav"], emit)
    from ..spec import glossary

    row = {"id": job.id, "source_type": job.source_type, "source": job.source,
           "settings_json": job.settings_json, "title": job.title, "glossary": glossary.load()}
    emit("cloud", -1, "Starting the cloud GPU…")
    t0 = time.time()
    result = _relay(_fn("analyze").remote_gen(row, start, end, captions, stages), emit)
    emit("cloud", 1.0, f"Cloud analysis done in {time.time() - t0:.0f} s")
    pull_job(job_dir, emit)
    return result


def build_specs(job_dir: Path, clips: list[int], captions: str | None, emit: Emit) -> None:
    """Smart camera + spec for several scored clips, one container each, in parallel."""
    job_dir = Path(job_dir)
    push_files(job_dir, ["score.json", "clip_edits.json"], emit)
    emit("spec", -1, f"Directing the camera for {len(clips)} clips in parallel…")
    done = 0
    from ..spec import glossary

    words = glossary.load()
    for _ in _fn("build_spec").starmap([(job_dir.name, c, captions, words) for c in clips]):
        done += 1
        emit("spec", done / len(clips), f"Clip {done}/{len(clips)} ready")
    pull_job(job_dir, emit, only="studio")


def second_opinion(job_dir: Path, words: list[dict], spans: list[dict], hotwords: str) -> list[dict]:
    """Run the Swahili second listen on a Modal GPU (seconds, vs minutes on a laptop CPU)."""
    job_dir = Path(job_dir)
    try:
        have = {e.path.rsplit("/", 1)[-1] for e in _volume().listdir(f"/jobs/{job_dir.name}")}
    except Exception:  # noqa: BLE001 — never sent to the cloud yet
        have = set()
    if "audio16k.wav" not in have:
        push_files(job_dir, ["audio16k.wav"], lambda *a: None)
    return _fn("second_listen").remote(job_dir.name, {"words": words, "spans": spans, "hotwords": hotwords})


def render(job_dir: Path, clip: int, emit: Emit) -> Path:
    """Upload the clip's spec + assets (and media if the volume lacks it),
    render on Modal, download render.mp4."""
    from ..spec import store

    job_dir = Path(job_dir)
    clip_rel = f"studio/clip_{clip:02d}"
    rels = [f"{clip_rel}/spec.json"]
    assets = store.clip_dir(job_dir, clip) / "assets"
    if assets.is_dir():
        rels += [f"{clip_rel}/assets/{p.name}" for p in assets.iterdir() if p.is_file()]
    spec = store.load(job_dir, clip) or {}
    src = (spec.get("source") or {}).get("src", "media.mp4")
    try:
        have = {e.path.rsplit("/", 1)[-1] for e in _volume().listdir(f"/jobs/{job_dir.name}")}
    except Exception:  # noqa: BLE001 — a job never sent to the cloud has no folder yet
        have = set()
    if PurePosixPath(src).name not in have:
        rels.append(src)
    push_files(job_dir, rels, emit)
    emit("render", -1, "Starting the cloud renderer…")
    _relay(_fn("render").remote_gen(f"{REMOTE_HOME}/jobs/{job_dir.name}", clip), emit)
    out = store.clip_dir(job_dir, clip) / "render.mp4"
    tmp = out.with_suffix(".part.mp4")
    with open(tmp, "wb") as fh:
        _volume().read_file_into_fileobj(_remote_rel(job_dir.name, f"{clip_rel}/render.mp4"), fh)
    tmp.replace(out)
    return out
