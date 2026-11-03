"""Studio: the spec editor's API (registered on the same /api/cmd/<name> route).

The editor (studio/editor) shows one clip at a time: a live Remotion Player
of the clip's spec.json, the transcript, and a chat with Claude Code. Every
change — a click in the editor or an edit by Claude — lands in spec.json and
is pushed to the browser as {"event": "spec", job_id, clip, spec}.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..spec import store
from . import agent, studio_chat
from .app import _job_ended, _job_started, CommandError, _read_json, _SAFE_NAME, command, events, home_dir, is_admin, stream_pipeline, workspace_dir

STUDIO_DIST = Path(os.environ.get("TETCLIPPER_STUDIO_DIST") or Path(__file__).resolve().parents[3] / "studio" / "editor" / "dist")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


log = logging.getLogger(__name__)

THUMB_VERTICAL, THUMB_LANDSCAPE = (360, 640), (640, 360)


def _thumb_inputs(job_dir: Path, clip: int) -> list[Path]:
    cdir = store.clip_dir(job_dir, clip)
    return [p for p in (store.spec_path(job_dir, clip), cdir / "render.mp4") if p.exists()]


def _thumb_version(job_dir: Path, clip: int) -> int:
    """Changes whenever the thumbnail would: the card's image URL carries it."""
    return int(max((p.stat().st_mtime for p in _thumb_inputs(job_dir, clip)), default=0))


def _crop_at(spec: dict, t: float) -> dict:
    """The camera path at source time t (VideoLayer.tsx cropAt)."""
    kfs = (spec.get("crop") or {}).get("keyframes") or []
    if not kfs:
        return {"x": 0.5, "y": 0.5, "zoom": 1}
    if t <= kfs[0]["t"]:
        return kfs[0]
    for a, b in zip(kfs, kfs[1:]):
        if t >= b["t"]:
            continue
        if b.get("cut") or b["t"] <= a["t"]:
            return a
        p = (t - a["t"]) / (b["t"] - a["t"])
        return {k: a[k] + (b[k] - a[k]) * p for k in ("x", "y", "zoom")}
    return kfs[-1]


def thumbnail(job_id: str, clip: int) -> Path | None:
    """A frame of the clip as it will look, kept next to its spec and
    remade when the spec or render changes: from the render when there is
    one, else the source framed by the clip's camera path a second in."""
    from ..render import ffmpeg_bin

    job_dir = _job_dir(job_id)
    spec = store.load(job_dir, clip)
    if spec is None:
        return None
    THUMB_W, THUMB_H = THUMB_LANDSCAPE if spec.get("format") == "landscape" else THUMB_VERTICAL
    out = store.clip_dir(job_dir, clip) / "thumb.jpg"
    if out.exists() and out.stat().st_mtime >= _thumb_version(job_dir, clip):
        return out
    render = store.clip_dir(job_dir, clip) / "render.mp4"
    if render.exists():
        src, t, vf = render, 1.0, f"scale={THUMB_W}:{THUMB_H}"
    else:
        source = spec["source"]
        src = job_dir / source["src"]
        t = source["start"] + min(1.0, (source["end"] - source["start"]) / 2)
        for cut in spec.get("cuts") or []:  # not a frame the clip cuts out
            if cut["start"] <= t < cut["end"]:
                t = cut["end"] + 0.1
        crop, sw, sh = _crop_at(spec, t), source["width"], source["height"]
        scale = max(THUMB_W / sw, THUMB_H / sh) * crop["zoom"]
        vw, vh = max(THUMB_W, round(sw * scale)), max(THUMB_H, round(sh * scale))
        left = min(vw - THUMB_W, max(0, round(crop["x"] * vw - THUMB_W / 2)))
        top = min(vh - THUMB_H, max(0, round(crop["y"] * vh - THUMB_H / 2)))
        vf = f"scale={vw}:{vh},crop={THUMB_W}:{THUMB_H}:{left}:{top}"
    if not src.exists():
        return None
    part = out.with_name(f"thumb.{os.getpid()}.{threading.get_ident()}.jpg")
    try:
        subprocess.run([ffmpeg_bin.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(src),
                        "-frames:v", "1", "-vf", vf, "-q:v", "4", str(part)],
                       capture_output=True, timeout=30, check=True)
        part.replace(out)
    except (subprocess.SubprocessError, OSError):
        part.unlink(missing_ok=True)
        return None
    return out


def _job_dir(job_id: str) -> Path:
    job_dir = workspace_dir() / "jobs" / Path(job_id).name
    if not job_dir.is_dir():
        raise CommandError(f"no job {job_id}")
    return job_dir


def _title(job_dir: Path) -> str:
    ingest = (_read_json(job_dir / "ingest.json") or {}).get("data") or {}
    return ingest.get("title") or job_dir.name


def _public_history(job_dir: Path, clip: int) -> list[dict]:
    """Version history for the browser; older AI edits were saved as "claude: ..."."""
    return [{**h, "reason": re.sub(r"(?i)^claude\b", "ai", h["reason"])} for h in store.history(job_dir, clip)]


def _publish_spec(job_dir: Path, clip: int, spec: dict, source: str) -> None:
    # job_dir is <workspace>/jobs/<id>: only that workspace's browsers get it.
    events.publish({"event": "spec", "job_id": job_dir.name, "clip": clip, "spec": spec, "source": source,
                    "history": _public_history(job_dir, clip)[-1:]}, job_dir.parents[1])


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
                store.save(job_dir, clip, spec, reason="ai")
                self.note(job_dir, clip)
                _publish_spec(job_dir, clip, spec, "ai")


watcher = _Watcher()


# ---------- commands ----------

STALE_SEC = 30 * 60  # a running job silent this long was cut off (server restart)


def _job_progress(job_dir: Path) -> dict | None:
    """The job's last step (server/app.py _JobProgress), or None for jobs from
    before progress files existed."""
    progress = _read_json(job_dir / "progress.json")
    if not isinstance(progress, dict):
        return None
    if progress.get("state") == "running" and time.time() - float(progress.get("updated") or 0) > STALE_SEC:
        progress.update(state="failed", error="This job stopped partway (the server restarted). Start it again.")
    return progress


@command
def studio_job_dismiss(jobId: str) -> None:
    """Hide a failed job's card from In progress."""
    job_dir = _job_dir(jobId)
    progress = _read_json(job_dir / "progress.json")
    if isinstance(progress, dict):
        progress["state"] = "dismissed"
        (job_dir / "progress.json").write_text(json.dumps(progress), encoding="utf-8")


@command
def studio_jobs() -> list[dict]:
    """Every job with Studio clips, newest first."""
    root = workspace_dir() / "jobs"
    out = []
    for job_dir in sorted(root.iterdir() if root.is_dir() else [], reverse=True):
        clips = store.list_clips(job_dir)
        settings = _read_json(job_dir / "settings.json") or {}
        progress = _job_progress(job_dir)
        active = progress is not None and progress["state"] in ("running", "failed")
        if not clips and not settings.get("section") and not active:
            continue
        scored = ((_read_json(job_dir / "score.json") or {}).get("data") or {}).get("clips") or []
        probe = ((_read_json(job_dir / "ingest.json") or {}).get("data") or {}).get("probe") or {}
        out.append({
            "id": job_dir.name,
            "title": _title(job_dir),
            "section": settings.get("section"),
            "progress": progress,
            # the source's short side: the p in 480p, landscape or vertical
            "res": min((v for v in (probe.get("width"), probe.get("height")) if v), default=None),
            "clips": [
                {
                    "clip": c,
                    "rendered": (store.clip_dir(job_dir, c) / "render.mp4").exists(),
                    "thumb": _thumb_version(job_dir, c),
                    "style": (store.load(job_dir, c) or {}).get("captions", {}).get("style"),
                    # auto-found moments carry the judge's score and summary
                    "score": None if c >= len(scored) or scored[c].get("manual") else scored[c].get("score"),
                    "summary": None if c >= len(scored) or scored[c].get("manual") else scored[c].get("summary"),
                }
                for c in clips
            ],
        })
    return out


_previews_making: set[str] = set()
_previews_failed: set[str] = set()
_previews_lock = threading.Lock()
_one_preview_at_a_time = threading.Semaphore(1)  # the web server has one CPU


def _preview_state(job_dir: Path, spec: dict) -> tuple[str | None, bool]:
    """(light preview copy's src if it exists, whether one is being made). Online
    only: on the desktop the original is a local file. Opening a clip starts the
    copy, so videos nobody edits never cost anything."""
    from ..cloud import client
    from ..spec import preview

    if not client.hosted():
        return None, False
    out = job_dir / preview.NAME
    if out.exists():
        return preview.NAME, False
    media = job_dir / spec["source"]["src"]
    key = str(job_dir)
    with _previews_lock:
        if key in _previews_failed or not media.exists():
            return None, False
        if key in _previews_making:
            return None, True
        _previews_making.add(key)

    def work() -> None:
        _job_started()  # a tab may close meanwhile: keep the container up until it's done
        try:
            with _one_preview_at_a_time:
                preview.make(media, out, int(spec["source"].get("width", 1920)), int(spec["source"].get("height", 1080)))
        except Exception as err:  # noqa: BLE001 — the original still plays, just slowly
            log.warning("preview copy failed for %s: %s", job_dir.name, err)
            with _previews_lock:
                _previews_failed.add(key)
        finally:
            _job_ended()
            with _previews_lock:
                _previews_making.discard(key)

    threading.Thread(target=work, daemon=True).start()
    return None, True


@command
def studio_preview(jobId: str, clip: int = 0) -> dict:
    """Is the light copy ready? The editor asks while it waits: a live event can be
    lost on the slow connections the copy is for."""
    job_dir = _job_dir(jobId)
    src, making = _preview_state(job_dir, store.load(job_dir, clip) or {"source": {"src": ""}})
    return {"preview": src, "previewing": making}


@command
def studio_clip(jobId: str, clip: int = 0) -> dict:
    job_dir = _job_dir(jobId)
    spec = store.load(job_dir, clip)
    if spec is None:
        raise CommandError("This clip has no spec yet (still processing?).")
    watcher.watch(job_dir, clip)
    render = _read_json(store.clip_dir(job_dir, clip) / "render.json")
    engine = agent.engine_label()
    available = engine["ready"] and (engine["provider"] != "claude-code" or studio_chat.find_claude() is not None)
    notice = None if available else studio_chat.not_ready_notice(engine)
    preview_src, previewing = _preview_state(job_dir, spec)
    return {
        "jobId": job_dir.name,
        "jobDir": str(job_dir),
        "clip": clip,
        "title": _title(job_dir),
        "spec": spec,
        "preview": preview_src,
        "previewing": previewing,
        "history": _public_history(job_dir, clip),
        "chat": {**studio_chat.public_history(job_dir, clip), "busy": studio_chat.busy(job_dir, clip),
                 "available": available, "notice": notice},
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
    return {"spec": saved, "history": _public_history(job_dir, clip)}


@command
def studio_undo(jobId: str, clip: int) -> dict:
    job_dir = _job_dir(jobId)
    spec = store.undo(job_dir, clip)
    if spec is None:
        raise CommandError("Nothing to undo.")
    watcher.note(job_dir, clip)
    _publish_spec(job_dir, clip, spec, "undo")
    return {"spec": spec, "history": _public_history(job_dir, clip)}


@command
def studio_info() -> dict:
    from ..cloud import client

    # hosted: the web app has no GPU, so there is no "this machine" to choose.
    return {"cloud": client.available(), "hosted": client.hosted()}


def _where(cloud: bool | None) -> list[str]:
    """--cloud/--local for the CLI. Online it is always the cloud: the web
    server has no GPU, whatever an older open tab asks for."""
    from ..cloud import client

    if client.hosted():
        return ["--cloud"]
    return [] if cloud is None else ["--cloud" if cloud else "--local"]


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
    stream_pipeline(args + _where(cloud))


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
    stream_pipeline(args + _where(cloud))


@command
def studio_long(source: str, start: float | None = None, end: float | None = None,
                language: str | None = None, cloud: bool | None = None) -> None:
    """A full horizontal video: fetch it, transcribe it, make it one project."""
    args = ["long", source]
    if start is not None and end is not None:
        args += ["--start", str(start), "--end", str(end)]
    if language:
        args += ["--language", language]
    stream_pipeline(args + _where(cloud))


def _asset_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    return "image" if suffix in IMAGE_EXTS else "video" if suffix in VIDEO_EXTS else "audio"


def _probe_media(path: Path) -> dict:
    """Length in seconds and whether a media file has sound (empty if unreadable:
    the browser can still read the length when it loads the file)."""
    from ..render.ffmpeg_bin import ffprobe

    try:
        run = subprocess.run(
            [ffprobe(), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(run.stdout or "{}")
        return {"duration": float(data.get("format", {}).get("duration") or 0),
                "hasAudio": any(s.get("codec_type") == "audio" for s in data.get("streams", []))}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


@command
def studio_attach(jobId: str, clip: int, path: str) -> dict:
    """Copy an uploaded image, video or audio file (or a library track) into the
    clip's assets/; returns its spec src, what it is and, for media, its length
    and whether it has sound."""
    job_dir = _job_dir(jobId)
    src = Path(path).resolve()
    roots = [workspace_dir().resolve(), (home_dir() / "audio").resolve()]  # own uploads or a library track
    if not any(root in src.parents for root in roots) or not src.is_file():
        raise CommandError("upload not found")
    if src.suffix.lower() not in IMAGE_EXTS | AUDIO_EXTS | VIDEO_EXTS:
        raise CommandError("Use an image (JPG, PNG, WebP, GIF), a video (MP4, MOV, WebM) or audio (MP3, WAV, M4A, OGG, FLAC).")
    assets = store.clip_dir(job_dir, clip) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    stem = _SAFE_NAME.sub("_", src.stem) or "image"
    dest = assets / f"{stem}{src.suffix.lower()}"
    n = 1
    while dest.exists():
        dest = assets / f"{stem}-{n}{src.suffix.lower()}"
        n += 1
    shutil.copyfile(src, dest)
    out: dict[str, Any] = {"src": dest.relative_to(job_dir).as_posix(), "kind": _asset_kind(dest)}
    if out["kind"] != "image":
        out.update(_probe_media(dest))
    return out


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
def studio_dead_air(jobId: str, clip: int, mode: str = "natural", fillers: bool = False, apply: bool = False) -> dict:
    """Preview (or apply) dead-air cuts for a clip."""
    from ..spec import silence

    job_dir = _job_dir(jobId)
    spec = store.load(job_dir, clip)
    if spec is None:
        raise CommandError("This clip has no spec yet.")
    if mode not in silence.MODES:
        raise CommandError(f"mode must be one of {', '.join(silence.MODES)}")
    found = silence.find(spec, job_dir, mode, fillers)
    out = {"cuts": len(found["cuts"]), "saved": found["saved"], "fillers": len(found["filler_words"])}
    if apply and (found["cuts"] or found["filler_words"]):
        reason = f"remove dead air ({mode}): {len(found['cuts'])} cuts, -{found['saved']:.1f}s"
        saved = store.save(job_dir, clip, silence.apply(spec, found), reason=reason)
        watcher.note(job_dir, clip)
        _publish_spec(job_dir, clip, saved, "editor")
        out.update(spec=saved, history=_public_history(job_dir, clip))
    return out


@command
def studio_stutters(jobId: str, clip: int, fillers: bool = False, apply: bool = False) -> dict:
    """Preview (or apply) stutter / false-start removal for a clip."""
    from ..spec import stutters

    job_dir = _job_dir(jobId)
    spec = store.load(job_dir, clip)
    if spec is None:
        raise CommandError("This clip has no spec yet.")
    found = stutters.find(spec, fillers)
    out = {"found": len(found["removals"]), "saved": found["saved"],
           "removals": [{"at": round(spec["words"][r["from"]]["start"], 2), "kind": r["kind"], "text": r["text"]} for r in found["removals"]]}
    if apply and found["removals"]:
        saved = store.save(job_dir, clip, stutters.apply(spec, found),
                           reason=f"remove stutters: {len(found['removals'])}, -{found['saved']:.1f}s")
        watcher.note(job_dir, clip)
        _publish_spec(job_dir, clip, saved, "editor")
        out.update(spec=saved)
    return out


@command
def studio_settings(allow_scripts: bool | None = None) -> dict:
    """Studio preferences (~/.tetclipper/studio.json). allow_scripts lets the
    chat's Claude run Python/Node scripts — off by default."""
    path = workspace_dir() / "studio.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(path) or {}
    if allow_scripts is not None:
        data["allow_scripts"] = bool(allow_scripts)
        path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return {"allow_scripts": bool(data.get("allow_scripts", False))}


@command
def studio_matte(jobId: str, clip: int) -> None:
    """Cut the speaker out of a clip (behind-the-speaker effects)."""
    job_dir = _job_dir(jobId)
    watcher.watch(job_dir, clip)
    stream_pipeline(["spec", "matte", job_dir.name, "--clip", str(clip)])


@command
def studio_doubts(jobId: str, clip: int) -> None:
    """Re-check a clip's captions (doubtful spans + a Swahili second listen)."""
    job_dir = _job_dir(jobId)
    watcher.watch(job_dir, clip)
    stream_pipeline(["spec", "doubts", job_dir.name, "--clip", str(clip)])


@command
def glossary_get() -> dict:
    from ..spec import glossary

    data = glossary.load()
    have = {glossary.norm(p) for p in data["phrases"]}
    return {**data, "suggestions": [p for p in glossary.SEED_PHRASES if glossary.norm(p) not in have]}


@command
def glossary_save(data: dict) -> dict:
    from ..spec import glossary

    glossary.save(data)
    return glossary_get()


@command
def studio_chat_send(jobId: str, clip: int, message: str, context: dict | None = None) -> None:
    job_dir = _job_dir(jobId)
    if not message.strip():
        raise CommandError("Type a message.")
    watcher.watch(job_dir, clip)

    def on_turn_end() -> list[str]:
        spec, problems = store.sync_from_disk(job_dir, clip, reason=f"ai: {message.strip()[:60]}")
        watcher.note(job_dir, clip)
        if spec is not None:
            _publish_spec(job_dir, clip, spec, "ai")
        return problems

    def save_spec(spec: dict, reason: str) -> dict:
        """API agent edits: validated by store.save (ValueError on problems)."""
        saved = store.save(job_dir, clip, spec, reason=reason)
        watcher.note(job_dir, clip)
        _publish_spec(job_dir, clip, saved, "ai")
        return saved

    try:
        studio_chat.send(job_dir, clip, _title(job_dir), message.strip(), context,
                         lambda event: events.publish(event, job_dir.parents[1]), on_turn_end,
                         allow_scripts=studio_settings()["allow_scripts"], save_spec=save_spec)
    except RuntimeError as err:
        raise CommandError(str(err)) from err


@command
def studio_chat_reset(jobId: str, clip: int) -> None:
    studio_chat.reset(_job_dir(jobId), clip)


# ---------- AI model (admin): provider, model and API key for every user ----------

def _admin_only() -> None:
    if not is_admin():
        raise CommandError("Only the admin can change the AI model.")


@command
def ai_settings_get() -> dict:
    _admin_only()
    return agent.public_settings()


@command
def ai_settings_save(provider: str, model: str = "", key: str | None = None, clear_key: bool = False,
                     base_url: str | None = None, price_in: float | None = None, price_out: float | None = None) -> dict:
    _admin_only()
    try:
        return agent.save_settings(provider, model, key, clear_key, base_url, price_in, price_out)
    except ValueError as err:
        raise CommandError(str(err)) from err


@command
def ai_models(provider: str, key: str | None = None, base_url: str | None = None) -> list[str]:
    _admin_only()
    try:
        return agent.list_models(provider, key, base_url)
    except ValueError as err:
        raise CommandError(str(err)) from err
    except ImportError as err:
        raise CommandError(f"The {provider} client library isn't installed on the server ({err.name}).") from err


@command
def ai_test(provider: str, model: str, key: str | None = None, base_url: str | None = None) -> dict:
    _admin_only()
    return agent.test(provider, model, key, base_url)
