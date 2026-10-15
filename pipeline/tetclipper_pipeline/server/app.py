"""Web shell: the same commands the Tauri desktop shell exposes, over HTTP.

The React UI (app/) talks to this when it runs in a plain browser:
  POST /api/cmd/<name>   one command, JSON args in, JSON out (400 + text on error,
                         mirroring a rejected Tauri invoke)
  GET  /api/events       Server-Sent Events: every `tetclipper --jsonl` line,
                         the same payloads the desktop app gets as `pipeline-event`
  GET  /files?path=...   a file under TETCLIPPER_HOME (byte ranges for <video>)
  POST /api/upload       raw request body -> TETCLIPPER_HOME/uploads/<name>
and, when app/dist exists, the built UI itself at /.

Like the Rust shell (app/src-tauri/src/main.rs), it is a thin proxy: anything
heavier than a file read shells out to the `tetclipper` CLI.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets as _secrets_mod
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

PIPELINE_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = PIPELINE_DIR.parent
DIST_DIR = Path(os.environ.get("TETCLIPPER_DIST") or REPO_DIR / "app" / "dist")
# Set on a hosted deployment: every /api and /files request must carry it
# (Authorization: Bearer … or the pc_token cookie the login screen sets).
WEB_TOKEN = os.environ.get("TETCLIPPER_WEB_TOKEN") or None
COOKIE = "pc_token"


def home_dir() -> Path:
    custom = os.environ.get("TETCLIPPER_HOME")
    return Path(custom) if custom else Path.home() / ".tetclipper"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        raw = path.read_bytes()
    except OSError:
        return default
    # Older Windows checkpoints were written in the ANSI codepage, not UTF-8.
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, ValueError):
            continue
    return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


# ---------- the pipeline CLI ----------

def cli_command(args: list[str]) -> list[str]:
    """`uv --directory pipeline run tetclipper ...` — the dev invocation the
    Rust shell uses, so the CLI keeps managing its own dependency groups.
    TETCLIPPER_CLI overrides the whole prefix (a container with the deps
    already installed runs `python -m tetclipper_pipeline.cli`)."""
    override = os.environ.get("TETCLIPPER_CLI")
    if override:
        return [*shlex.split(override), *args]
    uv = os.environ.get("TETCLIPPER_UV") or shutil.which("uv") or "uv"
    return [uv, "--directory", str(PIPELINE_DIR), "run", "tetclipper", *args]


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def run_cli_json(args: list[str]) -> Any:
    """Run the CLI and parse its last JSON line (edit/ig/audio contract)."""
    out = subprocess.run(
        cli_command(args), capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=_NO_WINDOW,
    )
    for line in reversed(out.stdout.splitlines()):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    raise CommandError(f"tetclipper produced no JSON: {out.stderr[:400]}")


class Broadcaster:
    """Fan pipeline events out to every open /api/events stream."""

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def publish(self, event: dict) -> None:
        # Called from worker threads.
        if self.loop is None:
            return
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, event)


events = Broadcaster()


# Pipeline runs alive in THIS process. A restarted server (a preempted cloud
# container) starts empty, which is how the UI learns a run it was watching
# is gone even though the "result" event never reached it.
_active: set[int] = set()
_active_lock = threading.Lock()


def stream_pipeline(args: list[str]) -> None:
    """Spawn `tetclipper --jsonl <args>` on a thread and broadcast its lines.
    Same `exited` rule as the Rust shell: only when no `result` was seen."""

    def work() -> None:
        token = id(threading.current_thread())
        with _active_lock:
            _active.add(token)
        try:
            _run()
        finally:
            with _active_lock:
                _active.discard(token)

    def _run() -> None:
        try:
            child = subprocess.Popen(
                cli_command(["--jsonl", *args]), stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", creationflags=_NO_WINDOW,
            )
        except OSError as err:
            events.publish({"event": "result", "ok": False, "error": f"could not start pipeline: {err}"})
            return
        saw_result = False
        assert child.stdout is not None
        for line in child.stdout:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                saw_result |= value.get("event") == "result"
                events.publish(value)
        code = child.wait()
        if code != 0 and not saw_result:
            events.publish({"event": "exited", "code": code})

    threading.Thread(target=work, daemon=True).start()


# ---------- commands (names/args match the Tauri commands) ----------

class CommandError(Exception):
    pass


COMMANDS: dict[str, Callable[..., Any]] = {}


def command(fn: Callable[..., Any]) -> Callable[..., Any]:
    COMMANDS[fn.__name__] = fn
    return fn


def _opt(flag: str, value: Any) -> list[str]:
    return [flag, str(value)] if value not in (None, "") else []


@command
def run_job(source: str, llm: str | None = None, captions: str | None = None,
            language: str | None = None) -> None:
    stream_pipeline(["run", source, *_opt("--llm", llm), *_opt("--captions", captions),
                     *_opt("--language", language)])


@command
def resume_job(jobId: str, llm: str | None = None, captions: str | None = None, camera: str | None = None) -> None:
    stream_pipeline(["resume", jobId, *_opt("--llm", llm), *_opt("--captions", captions), *_opt("--camera", camera)])


@command
def job_results(jobId: str) -> dict:
    job_dir = home_dir() / "jobs" / Path(jobId).name
    if not job_dir.exists():
        raise CommandError(f"no job dir for {jobId}")

    def stage(name: str) -> Any:
        return (_read_json(job_dir / f"{name}.json") or {}).get("data")

    return {
        "job_id": jobId,
        "dir": str(job_dir),
        **{name: stage(name) for name in ("ingest", "score", "camera", "render", "events", "candidates")},
    }


def _render_skipped() -> bool:
    return "render" in {s.strip() for s in os.environ.get("TETCLIPPER_SKIP_STAGES", "").split(",")}


@command
def chat_history(jobId: str) -> dict:
    from . import chat

    job_dir = home_dir() / "jobs" / Path(jobId).name
    return {**chat.history(job_dir), "available": chat.available()}


@command
def chat_send(jobId: str, message: str) -> None:
    from . import chat

    job_dir = home_dir() / "jobs" / Path(jobId).name
    ingest = (_read_json(job_dir / "ingest.json") or {}).get("data") or {}
    if not ingest:
        raise CommandError("This video hasn't been transcribed yet.")
    meta = {"title": ingest.get("title"), "duration": (ingest.get("probe") or {}).get("duration_sec")}
    try:
        chat.send(job_dir, meta, message.strip(), events.publish)
    except RuntimeError as err:
        raise CommandError(str(err)) from err


@command
def chat_reset(jobId: str) -> None:
    from . import chat

    chat.reset(home_dir() / "jobs" / Path(jobId).name)


@command
def pipeline_active() -> dict:
    """Whether any pipeline run is alive on this server right now."""
    with _active_lock:
        return {"running": len(_active)}


@command
def list_job_dirs() -> list[dict]:
    jobs_dir = home_dir() / "jobs"
    out = []
    for entry in jobs_dir.iterdir() if jobs_dir.exists() else []:
        if not entry.is_dir():
            continue
        ingest = _read_json(entry / "ingest.json") or {}
        rendered = (entry / "render.json").exists()
        out.append({
            "id": entry.name,
            "title": (ingest.get("data") or {}).get("title"),
            "ingested": (entry / "ingest.json").exists(),
            "rendered": rendered,
            # Hybrid hosting: analysed here, rendered on the user's machine.
            "pull_only": not rendered and _render_skipped() and (entry / "camera.json").exists(),
        })
    return sorted(out, key=lambda j: j["id"], reverse=True)


def _secrets() -> dict:
    return _read_json(home_dir() / "secrets.json", {}) or {}


def _merge_secret(key: str, value: Any) -> bool:
    path = home_dir() / "secrets.json"
    current = _secrets()
    current[key] = value.strip() if isinstance(value, str) else value
    _write_json(path, current)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


@command
def save_gemini_key(key: str) -> bool:
    return _merge_secret("gemini_api_key", key)


@command
def save_pexels_key(key: str) -> bool:
    return _merge_secret("pexels_api_key", key)


@command
def save_freesound_key(key: str) -> bool:
    return _merge_secret("freesound_key", key)


@command
def save_jamendo_key(key: str) -> bool:
    return _merge_secret("jamendo_client_id", key)


@command
def audio_keys_status() -> dict:
    s = _secrets()
    return {"has_freesound_key": bool(s.get("freesound_key")), "has_jamendo_key": bool(s.get("jamendo_client_id"))}


@command
def get_setup_state() -> dict:
    return {
        "has_gemini_key": bool(_secrets().get("gemini_api_key")),
        "onboarded": (home_dir() / "onboarded").exists(),
    }


@command
def mark_onboarded() -> None:
    home_dir().mkdir(parents=True, exist_ok=True)
    (home_dir() / "onboarded").write_text("1")


@command
def check_ollama() -> dict:
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            data = json.load(r)
    except Exception:
        return {"running": False, "models": []}
    return {"running": True, "models": [m.get("name") for m in data.get("models", []) if m.get("name")]}


@command
def edit_tool(args: list[str]) -> Any:
    return run_cli_json(["edit", *args])


@command
def run_edit_render(jobId: str, clip: int) -> None:
    stream_pipeline(["edit", "render-clip", jobId, str(clip)])


@command
def save_clip_edits(jobId: str, edits: dict) -> None:
    path = home_dir() / "jobs" / Path(jobId).name / "clip_edits.json"
    current = _read_json(path, {}) or {}
    current.update(edits)  # one clip at a time; keep the others
    _write_json(path, current)


@command
def job_transcript(jobId: str) -> Any:
    result = run_cli_json(["edit", "transcript", jobId])
    if not result.get("ok"):
        raise CommandError(result.get("error", "no transcript"))
    return result


@command
def add_clip_range(jobId: str, start: float, end: float, captions: str | None = None,
                   camera: str | None = None) -> None:
    stream_pipeline([
        "edit", "add-range", jobId, f"{start:.3f}", f"{end:.3f}",
        *_opt("--captions", captions), *_opt("--camera", camera),
    ])


@command
def telegram_status() -> Any:
    return run_cli_json(["telegram", "status"])


@command
def telegram_save_token(token: str) -> Any:
    return run_cli_json(["telegram", "token", token])


@command
def telegram_link() -> Any:
    return run_cli_json(["telegram", "link"])


@command
def telegram_send(jobId: str, clip: int, caption: str | None = None) -> Any:
    return run_cli_json(["telegram", "send", jobId, str(clip), *_opt("--caption", caption)])


@command
def server_info() -> dict:
    """What this server sees: handy when a hosted deployment misbehaves."""
    from .. import config

    return {
        "home": str(home_dir()),
        "dist": str(DIST_DIR),
        "dist_exists": DIST_DIR.exists(),
        "cli": cli_command([]),
        "device": config.compute_device(),
        "auth": bool(WEB_TOKEN),
    }


@command
def job_manifest(jobId: str) -> dict:
    """Everything a remote `tetclipper pull` needs: the job row and its files."""
    from ..jobs import queue

    job = queue.get_job(Path(jobId).name)
    if job is None:
        raise CommandError(f"no job {jobId}")
    files = [
        {"path": p.relative_to(job.dir).as_posix(), "size": p.stat().st_size}
        for p in sorted(job.dir.rglob("*")) if p.is_file()
    ]
    return {
        "home": home_dir().as_posix(),
        "job": {"id": job.id, "source_type": job.source_type, "source": job.source,
                "settings_json": job.settings_json, "title": job.title},
        "files": files,
    }


@command
def remote_jobs() -> dict:
    """Jobs on the hosted deployment (empty when none is configured)."""
    from ..jobs import remote

    if not remote.remote_url():
        return {"configured": False, "jobs": []}
    try:
        return {"configured": True, "url": remote.remote_url(), "jobs": remote.list_remote()}
    except Exception as err:  # noqa: BLE001 — offline / token problems show as a note
        return {"configured": True, "url": remote.remote_url(), "jobs": [], "error": str(err)}


@command
def cut_range(source: str, start: float, end: float, captions: str | None = None,
              camera: str | None = None, language: str | None = None) -> None:
    """Range mode: fetch only [start, end] and cut it (streams pipeline-event)."""
    stream_pipeline([
        "cut", source, f"{start:.3f}", f"{end:.3f}",
        *_opt("--captions", captions), *_opt("--camera", camera), *_opt("--language", language),
    ])


@command
def push_job(source: str, llm: str | None = None, captions: str | None = None) -> None:
    """Hybrid: download here, upload to the hosted GPU and start it there."""
    stream_pipeline(["push", source, *_opt("--llm", llm), *_opt("--captions", captions)])


@command
def pull_job(jobId: str) -> None:
    """Hybrid: pull a hosted job here and render it locally (streams events)."""
    stream_pipeline(["pull", jobId, "--render"])


@command
def brain_show(jobId: str) -> dict:
    """The Claude Code handoff over HTTP (hosted jobs): the pending request
    rendered as text, or null when the job isn't waiting."""
    from ..scoring import brain

    request = brain.load_request(home_dir() / "jobs" / Path(jobId).name)
    return {"waiting": request is not None, "text": brain.render_request(request) if request else None}


@command
def brain_answer(jobId: str, answers: dict) -> dict:
    from ..scoring import brain

    return brain.apply_answers(home_dir() / "jobs" / Path(jobId).name, answers)


@command
def run_audio_bootstrap() -> None:
    stream_pipeline(["audio", "bootstrap"])


@command
def audio_import(paths: list[str], kind: str) -> Any:
    return run_cli_json(["audio", "import", *paths, "--kind", kind])


@command
def audio_list(kind: str | None = None, query: str | None = None) -> Any:
    return run_cli_json(["audio", "list", "--json", *_opt("--kind", kind), *_opt("--query", query)])


@command
def audio_remove(id: str) -> Any:
    return run_cli_json(["audio", "remove", id])


@command
def audio_search(query: str, source: str, kind: str, maxDuration: float | None = None,
                 allowAttribution: bool = False) -> Any:
    return run_cli_json([
        "audio", "search", query, "--source", source, "--kind", kind, "--json",
        *_opt("--max-duration", maxDuration), *(["--allow-attribution"] if allowAttribution else []),
    ])


@command
def audio_fetch(source: str, sourceId: str) -> Any:
    return run_cli_json(["audio", "fetch", source, sourceId])


@command
def audio_suggest(jobId: str, clip: int) -> Any:
    return run_cli_json(["edit", "audio-suggest", jobId, str(clip)])


@command
def ig_status() -> dict:
    data = _read_json(home_dir() / "instagram.json")
    if not data:
        return {"connected": False}
    return {"connected": True, "username": data.get("username"), "obtained_at": data.get("token_obtained_at")}


@command
def ig_connect(appId: str, appSecret: str) -> str:
    raise CommandError("Instagram connect needs the desktop app (it catches a localhost OAuth callback).")


@command
def ig_tool(args: list[str]) -> Any:
    return run_cli_json(["ig", *args])


@command
def export_clip(path: str, title: str | None = None) -> str:
    # The browser downloads it; hand back the URL instead of copying to ~/Downloads.
    return f"/files?path={path}&download=1"


@command
def check_update() -> dict:
    return {"current": "web", "latest": None, "update_available": False, "url": ""}


# ---------- HTTP ----------

app = FastAPI(title="tetclipper")


@app.middleware("http")
async def _require_token(request: Request, call_next):
    # /api/login is how a browser gets the cookie, so it can't require it.
    path = request.url.path
    protected = path.startswith(("/api/", "/files")) and path != "/api/login"
    if WEB_TOKEN and protected:
        header = request.headers.get("authorization", "")
        given = header[7:] if header.lower().startswith("bearer ") else request.cookies.get(COOKIE, "")
        if not _secrets_mod.compare_digest(given, WEB_TOKEN):
            return JSONResponse({"error": "auth"}, status_code=401)
    return await call_next(request)


@app.post("/api/login")
async def login(request: Request) -> JSONResponse:
    """Trade the token for the cookie the SSE stream and <video> tags need."""
    body = await request.json()
    if WEB_TOKEN and not _secrets_mod.compare_digest(str(body.get("token", "")), WEB_TOKEN):
        return JSONResponse({"ok": False}, status_code=401)
    res = JSONResponse({"ok": True})
    if WEB_TOKEN:
        res.set_cookie(COOKIE, WEB_TOKEN, httponly=True, samesite="lax", secure=True, max_age=90 * 86400)
    return res


@app.on_event("startup")
async def _capture_loop() -> None:
    events.loop = asyncio.get_running_loop()


@app.post("/api/cmd/{name}")
async def run_command(name: str, request: Request) -> JSONResponse:
    fn = COMMANDS.get(name)
    if fn is None:
        raise HTTPException(404, f"unknown command {name}")
    body = await request.body()
    args = json.loads(body) if body else {}
    try:
        result = await asyncio.to_thread(fn, **(args or {}))
    except CommandError as err:
        return JSONResponse(str(err), status_code=400)
    except TypeError as err:  # wrong/missing args
        return JSONResponse(f"{name}: {err}", status_code=400)
    return JSONResponse(result)


@app.get("/api/events")
async def stream_events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    events.subscribers.add(queue)

    async def gen():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            events.subscribers.discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/files")
async def get_file(path: str, download: int = 0) -> FileResponse:
    # Only ever serve files inside TETCLIPPER_HOME.
    home = home_dir().resolve()
    file = Path(path).resolve()
    if home not in file.parents or not file.is_file():
        raise HTTPException(404)
    return FileResponse(file, filename=file.name if download else None)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@app.post("/api/upload")
async def upload(request: Request, name: str) -> dict:
    dest_dir = home_dir() / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem, ext = os.path.splitext(_SAFE_NAME.sub("_", Path(name).name) or "upload.mp4")
    dest = dest_dir / f"{stem}{ext}"
    n = 1
    while dest.exists():
        dest = dest_dir / f"{stem}-{n}{ext}"
        n += 1
    with dest.open("wb") as f:
        async for chunk in request.stream():
            f.write(chunk)
    return {"path": str(dest)}


from . import studio as _studio  # noqa: E402 — registers the studio_* commands

if _studio.STUDIO_DIST.exists():
    app.mount("/studio", StaticFiles(directory=_studio.STUDIO_DIST, html=True), name="studio")
if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="ui")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
