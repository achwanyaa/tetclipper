"""Web server: the Studio editor's API, plus the pipeline commands it shells out to.

The Studio editor (studio/editor, served at /studio/) talks to this:
  POST /api/cmd/<name>   one command, JSON args in, JSON out (400 + text on error)
  GET  /api/events       Server-Sent Events: every `tetclipper --jsonl` line
                         plus spec changes and chat streaming
  GET  /files?path=...   a file under TETCLIPPER_HOME (byte ranges for <video>)
  POST /api/upload       raw request body -> TETCLIPPER_HOME/uploads/<name>
  GET  /api/health       how many pipelines are running (no sign-in; for deploys)
and the built editor at /studio/ (/ redirects there).

It is a thin proxy: anything heavier than a file read shells out to the
`tetclipper` CLI.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets as _secrets_mod
import shlex
import shutil
import subprocess
import sys
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import config

PIPELINE_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = PIPELINE_DIR.parent
# Older hosted setup: one shared token on every /api and /files request
# (Authorization: Bearer … or the pc_token cookie the login screen sets).
WEB_TOKEN = os.environ.get("TETCLIPPER_WEB_TOKEN") or None
COOKIE = "pc_token"
# The online app: TETCLIPPER_AUTH=supabase. Every request carries the user's
# Supabase access token; each user works in their own workspace.
AUTH = os.environ.get("TETCLIPPER_AUTH", "").strip().lower()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
ADMINS = {e.strip().lower() for e in os.environ.get("TETCLIPPER_ADMINS", "").split(",") if e.strip()}
# Signs the long-lived media tokens that <video> tags and the event stream use
# (they can't send headers, and Supabase tokens expire hourly).
MEDIA_SECRET = (os.environ.get("TETCLIPPER_MEDIA_SECRET") or os.environ.get("SUPABASE_SECRET_KEY") or _secrets_mod.token_hex(32)).encode()
MEDIA_TTL = 24 * 3600
USER: ContextVar[dict | None] = ContextVar("tetclipper_user", default=None)


def home_dir() -> Path:
    """The shared home (models, secrets, AI settings). A user's own files live in workspace_dir()."""
    custom = os.environ.get("TETCLIPPER_HOME")
    return Path(custom) if custom else Path.home() / ".tetclipper"


def workspace_dir() -> Path:
    return config.workspace_dir()


def current_user() -> dict | None:
    return USER.get()


def is_admin() -> bool:
    """Everyone is the admin of the desktop app; online, the TETCLIPPER_ADMINS
    emails and users with app_metadata.role = admin are."""
    if AUTH != "supabase":
        return True
    user = USER.get()
    return bool(user and user.get("admin"))


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
    """Fan pipeline events out to the open /api/events streams. Online, each
    stream belongs to one workspace and only gets that workspace's events.

    Events carry ids ("<boot>-<n>") and the last REPLAY are kept, so a stream
    that reconnects (streams end every STREAM_SEC) gets what it missed. Ids
    from another container (an old version, before a deploy) replay nothing."""

    REPLAY = 300

    def __init__(self) -> None:
        self.subscribers: dict[asyncio.Queue, str | None] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.boot = _secrets_mod.token_hex(4)
        self.seq = 0
        self.recent: collections.deque[tuple[int, str | None, dict]] = collections.deque(maxlen=self.REPLAY)
        self.lock = threading.Lock()

    @staticmethod
    def _sees(owner: str | None, key: str | None) -> bool:
        return owner is None or key is None or owner == key

    def publish(self, event: dict, workspace: Path | None = None) -> None:
        # Called from worker threads; the workspace defaults to the caller's.
        if self.loop is None:
            return
        ws = workspace or config.WORKSPACE.get()
        key = str(ws) if ws else None
        with self.lock:
            self.seq += 1
            item = (self.seq, key, event)
            self.recent.append(item)
        for q, owner in list(self.subscribers.items()):
            if self._sees(owner, key):
                self.loop.call_soon_threadsafe(q.put_nowait, item)

    def missed(self, last_event_id: str | None, owner: str | None) -> list[tuple[int, str | None, dict]]:
        """Events after `last_event_id` this stream would have seen."""
        boot, _, n = (last_event_id or "").partition("-")
        if boot != self.boot or not n.isdigit():
            return []
        with self.lock:
            return [item for item in self.recent if item[0] > int(n) and self._sees(owner, item[1])]


events = Broadcaster()


def stream_pipeline(args: list[str]) -> None:
    """Spawn `tetclipper --jsonl <args>` on a thread and broadcast its lines.
    An `exited` event is published only when no `result` was seen. The CLI
    works in the caller's workspace."""
    ws = config.WORKSPACE.get()
    env = {**os.environ, "TETCLIPPER_WORKSPACE": str(ws)} if ws else None
    label = "Finding moments" if "find" in args else "Cutting a clip" if "cut" in args else None

    def _run() -> None:
        progress = _JobProgress(label)
        _job_started()
        try:
            try:
                child = subprocess.Popen(
                    cli_command(["--jsonl", *args]), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", creationflags=_NO_WINDOW, env=env,
                )
            except OSError as err:
                events.publish({"event": "result", "ok": False, "error": f"could not start pipeline: {err}"}, ws)
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
                    progress.track(value)
                    events.publish(value, ws)
            code = child.wait()
            if code != 0 and not saw_result:
                progress.track({"event": "exited", "code": code})
                events.publish({"event": "exited", "code": code}, ws)
        finally:
            _job_ended()

    threading.Thread(target=contextvars.copy_context().run, args=(_run,), daemon=True).start()


class _JobProgress:
    """<job dir>/progress.json: the job's latest step. The clip list reads it,
    so a running job shows up even when its live events never reached this
    browser (a reload, another device)."""

    def __init__(self, label: str | None) -> None:
        self.path: Path | None = None
        self.state: dict = {"state": "running", "fraction": 0.0, "message": "Starting…", "label": label}
        self.written = 0.0

    def track(self, event: dict) -> None:
        kind = event.get("event")
        if kind == "job" and event.get("dir") and self.path is None:
            self.path = Path(event["dir"]) / "progress.json"
            self._write(force=True)
        elif kind == "progress":
            if isinstance(event.get("fraction"), (int, float)) and event["fraction"] >= 0:
                self.state["fraction"] = float(event["fraction"])
            self.state["message"] = event.get("message") or self.state["message"]
            self._write()
        elif kind == "result":
            ok = bool(event.get("ok"))
            self.state.update(state="done" if ok else "failed", fraction=1.0, error=None if ok else event.get("error"))
            self._write(force=True)
        elif kind == "exited":
            self.state.update(state="failed", error=f"The job stopped unexpectedly (code {event.get('code')}).")
            self._write(force=True)

    def _write(self, force: bool = False) -> None:
        now = time.time()
        if self.path is None or (not force and now - self.written < 1.0):
            return
        self.written = now
        try:
            self.path.write_text(json.dumps({**self.state, "updated": now}), encoding="utf-8")
        except OSError:
            pass


# Modal scales the web container down 15 min after its last request, and a
# running pipeline isn't a request. While one runs, ask ourselves for
# something cheap every 4 minutes (TETCLIPPER_PUBLIC_URL; unset on the desktop).
_running = 0
_running_lock = threading.Lock()
_pinger: threading.Thread | None = None


def _job_started() -> None:
    global _running, _pinger
    with _running_lock:
        _running += 1
        if os.environ.get("TETCLIPPER_PUBLIC_URL") and _pinger is None:
            _pinger = threading.Thread(target=_keep_alive, daemon=True)
            _pinger.start()


def _job_ended() -> None:
    global _running
    with _running_lock:
        _running -= 1


def _keep_alive() -> None:
    global _pinger
    import httpx

    url = os.environ.get("TETCLIPPER_PUBLIC_URL", "").rstrip("/")
    while True:
        time.sleep(240)
        with _running_lock:
            if _running <= 0:
                _pinger = None
                return
        try:
            httpx.get(f"{url}/api/auth-config", timeout=30)
        except httpx.HTTPError:
            pass


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


# ---- online sign-in (Supabase) ----

_verified: dict[str, tuple[dict, float]] = {}


async def _supabase_user(token: str) -> dict | None:
    """The signed-in user behind a Supabase access token, checked with Supabase
    itself (so a revoked session stops working) and cached for 5 minutes."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    hit = _verified.get(digest)
    if hit and hit[1] > time.time():
        return hit[0]
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    if res.status_code != 200:
        return None
    data = res.json()
    email = (data.get("email") or "").lower()
    role = (data.get("app_metadata") or {}).get("role")
    user = {"id": data["id"], "email": email, "admin": email in ADMINS or role == "admin"}
    if len(_verified) > 500:
        _verified.clear()
    _verified[digest] = (user, time.time() + 300)
    return user


def media_token(user: dict) -> str:
    """mt.<payload>.<sig>: lets <video> tags and the event stream (which can't
    send headers) reach this user's files for a day."""
    payload = base64.urlsafe_b64encode(json.dumps({"id": user["id"], "exp": int(time.time()) + MEDIA_TTL}).encode()).decode().rstrip("=")
    sig = hmac.new(MEDIA_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"mt.{payload}.{sig}"


def _media_user(token: str) -> dict | None:
    try:
        _, payload, sig = token.split(".")
        if not hmac.compare_digest(sig, hmac.new(MEDIA_SECRET, payload.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError):
        return None
    return {"id": data["id"], "email": "", "admin": False} if data.get("exp", 0) > time.time() else None


_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


@app.middleware("http")
async def _require_token(request: Request, call_next):
    path = request.url.path
    public = ("/api/login", "/api/auth-config", "/api/health")
    protected = path.startswith(("/api/", "/files")) and path not in public and request.method != "OPTIONS"
    if AUTH == "supabase" and protected:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else request.query_params.get("access_token", "")
        if token.startswith("mt."):
            # Media tokens only open the read-only routes that can't send headers.
            user = _media_user(token) if path in ("/files", "/api/events") else None
        else:
            user = await _supabase_user(token) if token else None
        if not user or not _SAFE_ID.match(user["id"]):
            return JSONResponse({"error": "auth"}, status_code=401)
        USER.set(user)
        config.WORKSPACE.set(home_dir() / "users" / user["id"])
    elif WEB_TOKEN and protected:
        header = request.headers.get("authorization", "")
        given = header[7:] if header.lower().startswith("bearer ") else request.cookies.get(COOKIE, "")
        if not _secrets_mod.compare_digest(given, WEB_TOKEN):
            return JSONResponse({"error": "auth"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict:
    """Pipelines running here: modal_app.py won't deploy over a running job."""
    return {"running": _running}


@app.get("/api/auth-config")
async def auth_config() -> dict:
    """How the browser should sign in: none (desktop), supabase or token."""
    return {"mode": "supabase" if AUTH == "supabase" else "token" if WEB_TOKEN else "none"}


@command
def me() -> dict:
    """Who is signed in, whether they're the admin, and their media token."""
    user = USER.get()
    return {
        "mode": "supabase" if AUTH == "supabase" else "none",
        "user": {"id": user["id"], "email": user["email"]} if user else None,
        "admin": is_admin(),
        "media_token": media_token(user) if user else None,
    }


# The Vercel-hosted editor calls this API from another origin.
_cors = os.environ.get("TETCLIPPER_CORS_ORIGINS")  # a regex, e.g. https://tetclipper(-[a-z0-9-]+)?\.vercel\.app
if _cors:
    app.add_middleware(CORSMiddleware, allow_origin_regex=_cors, allow_methods=["*"], allow_headers=["*"], max_age=3600)


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


# Each event stream ends after this long and the browser reconnects (Last-Event-ID
# replays the gap). After a deploy that moves open tabs to the new version
# instead of leaving them listening to the old container forever.
STREAM_SEC = 10 * 60


@app.get("/api/events")
async def stream_events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    ws = config.WORKSPACE.get()
    owner = str(ws) if ws else None
    events.subscribers[queue] = owner
    backlog = events.missed(request.headers.get("last-event-id"), owner)

    async def gen():
        sent = backlog[-1][0] if backlog else 0
        ends = time.monotonic() + STREAM_SEC
        try:
            yield "retry: 1000\n: connected\n\n"
            for n, _, event in backlog:
                yield f"id: {events.boot}-{n}\ndata: {json.dumps(event)}\n\n"
            while time.monotonic() < ends and not await request.is_disconnected():
                try:
                    n, _, event = await asyncio.wait_for(queue.get(), timeout=15)
                    if n > sent:  # already replayed from the backlog
                        sent = n
                        yield f"id: {events.boot}-{n}\ndata: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            events.subscribers.pop(queue, None)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/files")
async def get_file(path: str, download: int = 0) -> FileResponse:
    # Only the user's own workspace, plus the shared music library. The
    # desktop app's workspace is the whole home.
    file = Path(path).resolve()
    roots = [workspace_dir().resolve(), (home_dir() / "audio").resolve()]
    if not any(root in file.parents for root in roots) or not file.is_file():
        raise HTTPException(404)
    return FileResponse(file, filename=file.name if download else None)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@app.post("/api/upload")
async def upload(request: Request, name: str) -> dict:
    dest_dir = workspace_dir() / "uploads"
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
