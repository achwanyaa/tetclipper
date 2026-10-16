"""Studio: the spec editor's API (registered on the same /api/cmd/<name> route).

The editor (studio/editor) shows one clip at a time: a live Remotion Player
of the clip's spec.json, the transcript, and a chat with Claude Code. Every
change — a click in the editor or an edit by Claude — lands in spec.json and
is pushed to the browser as {"event": "spec", job_id, clip, spec}.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from ..spec import store
from . import studio_chat
from .app import CommandError, _read_json, _SAFE_NAME, command, events, home_dir, stream_pipeline

STUDIO_DIST = Path(os.environ.get("TETCLIPPER_STUDIO_DIST") or Path(__file__).resolve().parents[3] / "studio" / "editor" / "dist")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def _job_dir(job_id: str) -> Path:
    job_dir = home_dir() / "jobs" / Path(job_id).name
    if not job_dir.is_dir():
        raise CommandError(f"no job {job_id}")
    return job_dir


def _title(job_dir: Path) -> str:
    ingest = (_read_json(job_dir / "ingest.json") or {}).get("data") or {}
    return ingest.get("title") or job_dir.name


def _publish_spec(job_dir: Path, clip: int, spec: dict, source: str) -> None:
    events.publish({"event": "spec", "job_id": job_dir.name, "clip": clip, "spec": spec, "source": source,
                    "history": store.history(job_dir, clip)[-1:]})


# ---------- live watcher: Claude edits spec.json directly ----------

class _Watcher:
    """Polls the spec.json of every clip the editor has open. A valid change
    made outside the API (Claude Code's Edit tool) is recorded in history and
    published; an invalid intermediate state is ignored until the turn ends."""

    def __init__(self) -> None:
        self.known: dict[tuple[str, int], str] = {}
        self.lock = threading.Lock()
        self.started = False

    def watch(self, job_dir: Path, clip: int) -> None:
        path = store.spec_path(job_dir, clip)
        with self.lock:
            self.known[(str(job_dir), clip)] = path.read_text(encoding="utf-8") if path.exists() else ""
            if not self.started:
                self.started = True
                threading.Thread(target=self._loop, daemon=True).start()

    def note(self, job_dir: Path, clip: int) -> None:
        """The API itself just wrote spec.json — don't re-publish it."""
        path = store.spec_path(job_dir, clip)
        with self.lock:
            self.known[(str(job_dir), clip)] = path.read_text(encoding="utf-8") if path.exists() else ""

    def _loop(self) -> None:
        from ..spec.schema import validate

        while True:
            time.sleep(0.4)
            with self.lock:
                items = list(self.known.items())
            for (job, clip), last in items:
                path = store.spec_path(Path(job), clip)
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                if text == last:
                    continue
                try:
                    spec = json.loads(text)
                except ValueError:
                    continue  # mid-write or broken; the end-of-turn check handles it
                if validate(spec):
                    continue
                job_dir = Path(job)
                store.save(job_dir, clip, spec, reason="claude")
                self.note(job_dir, clip)
                _publish_spec(job_dir, clip, spec, "claude")


watcher = _Watcher()


# ---------- commands ----------

@command
def studio_jobs() -> list[dict]:
    """Every job with Studio clips, newest first."""
    root = home_dir() / "jobs"
    out = []
    for job_dir in sorted(root.iterdir() if root.is_dir() else [], reverse=True):
        clips = store.list_clips(job_dir)
        settings = _read_json(job_dir / "settings.json") or {}
        if not clips and not settings.get("section"):
            continue
        scored = ((_read_json(job_dir / "score.json") or {}).get("data") or {}).get("clips") or []
        out.append({
            "id": job_dir.name,
            "title": _title(job_dir),
            "section": settings.get("section"),
            "clips": [
                {
                    "clip": c,
                    "rendered": (store.clip_dir(job_dir, c) / "render.mp4").exists(),
                    "style": (store.load(job_dir, c) or {}).get("captions", {}).get("style"),
                    # auto-found moments carry the judge's score and summary
                    "score": None if c >= len(scored) or scored[c].get("manual") else scored[c].get("score"),
                    "summary": None if c >= len(scored) or scored[c].get("manual") else scored[c].get("summary"),
                }
                for c in clips
            ],
        })
    return out


@command
def studio_clip(jobId: str, clip: int = 0) -> dict:
    job_dir = _job_dir(jobId)
    spec = store.load(job_dir, clip)
    if spec is None:
        raise CommandError("This clip has no spec yet (still processing?).")
    watcher.watch(job_dir, clip)
    render = _read_json(store.clip_dir(job_dir, clip) / "render.json")
    return {
        "jobId": job_dir.name,
        "jobDir": str(job_dir),
        "clip": clip,
        "title": _title(job_dir),
        "spec": spec,
        "history": store.history(job_dir, clip),
        "chat": {**studio_chat.history(job_dir, clip), "busy": studio_chat.busy(job_dir, clip),
                 "available": studio_chat._claude() is not None},  # noqa: SLF001
        "render": render,
    }


@command
def studio_save(jobId: str, clip: int, spec: dict, reason: str = "edit") -> dict:
    job_dir = _job_dir(jobId)
    try:
        saved = store.save(job_dir, clip, spec, reason=reason)
    except ValueError as err:
        raise CommandError(str(err)) from err
    watcher.note(job_dir, clip)
    _publish_spec(job_dir, clip, saved, "editor")
    return {"spec": saved, "history": store.history(job_dir, clip)}


@command
def studio_undo(jobId: str, clip: int) -> dict:
    job_dir = _job_dir(jobId)
    spec = store.undo(job_dir, clip)
    if spec is None:
        raise CommandError("Nothing to undo.")
    watcher.note(job_dir, clip)
    _publish_spec(job_dir, clip, spec, "undo")
    return {"spec": spec, "history": store.history(job_dir, clip)}


@command
def studio_info() -> dict:
    from ..cloud import client

    return {"cloud": client.available()}


@command
def studio_cut(source: str, start: float, end: float, captions: str | None = None,
               language: str | None = None, cloud: bool | None = None) -> None:
    """Range mode: fetch START–END here, analyse it (Modal GPU or this PC) and
    build the clip's spec."""
    args = ["cut", source, str(start), str(end)]
    if captions:
        args += ["--captions", captions]
    if language:
        args += ["--language", language]
    if cloud is not None:
        args.append("--cloud" if cloud else "--local")
    stream_pipeline(args)


@command
def studio_find(source: str, start: float | None = None, end: float | None = None, top: int = 5,
                captions: str | None = None, language: str | None = None, cloud: bool | None = None) -> None:
    """Auto-find the best moments (Claude Code judges) in a link, a section of
    it, or an existing job (source = job id), and make the top ones clips."""
    args = ["find", source]
    if start is not None and end is not None:
        args += [str(start), str(end)]
    args += ["--top", str(top)]
    if captions:
        args += ["--captions", captions]
    if language:
        args += ["--language", language]
    if cloud is not None:
        args.append("--cloud" if cloud else "--local")
    stream_pipeline(args)


@command
def studio_attach(jobId: str, clip: int, path: str) -> dict:
    """Copy an uploaded image or audio file (or a library track) into the
    clip's assets/; returns its spec src."""
    job_dir = _job_dir(jobId)
    src = Path(path).resolve()
    home = home_dir().resolve()
    if home not in src.parents or not src.is_file():
        raise CommandError("upload not found")
    if src.suffix.lower() not in IMAGE_EXTS | AUDIO_EXTS:
        raise CommandError("Use an image (JPG, PNG, WebP, GIF) or audio (MP3, WAV, M4A, OGG, FLAC).")
    assets = store.clip_dir(job_dir, clip) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    stem = _SAFE_NAME.sub("_", src.stem) or "image"
    dest = assets / f"{stem}{src.suffix.lower()}"
    n = 1
    while dest.exists():
        dest = assets / f"{stem}-{n}{src.suffix.lower()}"
        n += 1
    shutil.copyfile(src, dest)
    return {"src": dest.relative_to(job_dir).as_posix()}


@command
def studio_render(jobId: str, clip: int) -> None:
    job_dir = _job_dir(jobId)
    stream_pipeline(["spec", "render", job_dir.name, "--clip", str(clip)])


@command
def studio_telegram(jobId: str, clip: int, caption: str | None = None) -> Any:
    from ..delivery import telegram

    job_dir = _job_dir(jobId)
    out = store.clip_dir(job_dir, clip) / "render.mp4"
    if not out.exists():
        raise CommandError("Render the clip first.")
    try:
        return telegram.send_clip(out, caption or _title(job_dir))
    except Exception as err:  # noqa: BLE001 — surface Telegram's message
        raise CommandError(str(err)) from err


@command
def studio_chat_send(jobId: str, clip: int, message: str, context: dict | None = None) -> None:
    job_dir = _job_dir(jobId)
    if not message.strip():
        raise CommandError("Type a message.")
    watcher.watch(job_dir, clip)

    def on_turn_end() -> list[str]:
        spec, problems = store.sync_from_disk(job_dir, clip, reason=f"claude: {message.strip()[:60]}")
        watcher.note(job_dir, clip)
        if spec is not None:
            _publish_spec(job_dir, clip, spec, "claude")
        return problems

    try:
        studio_chat.send(job_dir, clip, _title(job_dir), message.strip(), context, events.publish, on_turn_end)
    except RuntimeError as err:
        raise CommandError(str(err)) from err


@command
def studio_chat_reset(jobId: str, clip: int) -> None:
    studio_chat.reset(_job_dir(jobId), clip)
