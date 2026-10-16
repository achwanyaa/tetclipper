"""Web server: the Studio editor's API, plus the pipeline commands it shells out to.

The Studio editor (studio/editor, served at /studio/) talks to this:
  POST /api/cmd/<name>   one command, JSON args in, JSON out (400 + text on error,
                         mirroring a rejected Tauri invoke)
  GET  /api/events       Server-Sent Events: every `tetclipper --jsonl` line
                         plus spec changes and chat streaming
  GET  /files?path=...   a file under TETCLIPPER_HOME (byte ranges for <video>)
  POST /api/upload       raw request body -> TETCLIPPER_HOME/uploads/<name>
and the built editor at /studio/ (/ redirects there).

It is a thin proxy: anything heavier than a file read shells out to the
`tetclipper` CLI.
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

PIPELINE_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = PIPELINE_DIR.parent
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
    """`uv --directory pipeline run tetclipper ...`, so the CLI keeps
    managing its own dependency groups.
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


def stream_pipeline(args: list[str]) -> None:
    """Spawn `tetclipper --jsonl <args>` on a thread and broadcast its lines.
    An `exited` event is published only when no `result` was seen."""

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

    threading.Thread(target=_run, daemon=True).start()


# ---------- commands (POST /api/cmd/<name>; Studio's are in server/studio.py) ----------

class CommandError(Exception):
    pass


COMMANDS: dict[str, Callable[..., Any]] = {}


def command(fn: Callable[..., Any]) -> Callable[..., Any]:
    COMMANDS[fn.__name__] = fn
    return fn


def _opt(flag: str, value: Any) -> list[str]:
    return [flag, str(value)] if value not in (None, "") else []


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


# ---- music library (Studio's Music tab) ----

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
def audio_list(kind: str | None = None, query: str | None = None) -> Any:
    return run_cli_json(["audio", "list", "--json", *_opt("--kind", kind), *_opt("--query", query)])


@command
def run_audio_bootstrap() -> None:
    stream_pipeline(["audio", "bootstrap"])


# ---- Telegram delivery setup (sending: studio_telegram) ----

@command
def telegram_status() -> Any:
    return run_cli_json(["telegram", "status"])


@command
def telegram_save_token(token: str) -> Any:
    return run_cli_json(["telegram", "token", token])


@command
def telegram_link() -> Any:
    return run_cli_json(["telegram", "link"])


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


@app.get("/")
async def _root() -> RedirectResponse:
    return RedirectResponse("/studio/")


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
