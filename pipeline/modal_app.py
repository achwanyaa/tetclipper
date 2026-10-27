"""tetclipper on Modal: the web shell + pipeline, plus the Studio functions.

    modal secret create tetclipper-web TETCLIPPER_WEB_TOKEN=<random>
    modal deploy pipeline/modal_app.py        # prints the https URL

Studio (driven from the PC by tetclipper_pipeline/cloud/client.py):
  analyze  GPU (T4, else L4/A10G): ASR → diarize → events → camera → clip spec for a range
           whose download/ingest the PC uploaded to the volume
  render   16 CPUs, node + Chromium: Remotion-renders a clip spec to mp4

Everything mutable (models, jobs, clips, secrets.json, llm-cache) lives on
the `tetclipper-home` Volume, mounted as TETCLIPPER_HOME. The web endpoint
serves the built Studio editor (studio/editor/dist) next to the API. Studio
chat needs the Claude Code CLI, so it only works in a local `tetclipper serve`.

There is one web container in normal use: live events, chat state and the
spec watcher live in its memory, so a second one would miss them (job
progress is also kept in progress.json and polled, so it survives that).
max_containers=4 is headroom for deploys only: old versions' containers count
against the limit while a browser tab holds their event stream open (streams
now end every 10 minutes, so they drain), and when they filled it the new
version couldn't start at all. Deploys wait for running jobs (see
_refuse_to_deploy_over_running_jobs). A container stays up while a tab is open
or a job is running (server/app.py pings TETCLIPPER_PUBLIC_URL), plus
SCALEDOWN seconds; jobs also checkpoint after every stage.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent  # pipeline/
REPO = HERE.parent
HOME = "/data"
PUBLIC_URL = "https://achwanyatours--tetclipper-web.us-east.modal.run"
# Cheapest first; Modal falls back down the list when it has no T4s free
# (a deploy once sat for minutes "waiting to be scheduled on a GPU_T4 worker").
GPU = os.environ.get("TETCLIPPER_MODAL_GPU", "T4,L4,A10G").split(",")
SCALEDOWN = 15 * 60

app = modal.App("tetclipper")
volume = modal.Volume.from_name("tetclipper-home", create_if_missing=True)


def _refuse_to_deploy_over_running_jobs() -> None:
    """A deploy moves new requests to a new container while a running job
    finishes in the old one, whose files the new one can't see until it
    restarts: the job looks stuck and its clips go missing for a while. So
    `modal deploy` waits for jobs to finish (TETCLIPPER_DEPLOY_ANYWAY=1 skips)."""
    if os.environ.get("TETCLIPPER_DEPLOY_ANYWAY") == "1":
        return
    import json
    import urllib.request

    try:
        if not modal.Function.from_name(app.name, "web").get_current_stats().num_total_runners:
            return  # no web container up, so nothing running
        with urllib.request.urlopen(f"{PUBLIC_URL}/api/health", timeout=30) as resp:
            running = json.load(resp).get("running", 0)
    except Exception:  # noqa: BLE001 — first deploy, older server, offline: don't block
        return
    if running:
        raise SystemExit(
            f"{running} job(s) running on the live server. Deploying now would cut them off from "
            "their users: try again when they finish, or set TETCLIPPER_DEPLOY_ANYWAY=1."
        )


if modal.is_local() and sys.argv[1:2] == ["deploy"]:
    _refuse_to_deploy_over_running_jobs()

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Debian's ffmpeg is built with libass → caption burning works out of the box.
    .apt_install("ffmpeg", "git", "libglib2.0-0", "libsndfile1")
    .uv_sync(uv_project_dir=str(HERE), groups=["pipeline", "server"], extras=[], frozen=True)
    .env({
        "TETCLIPPER_HOME": HOME,
        "TETCLIPPER_DEVICE": "cuda",
        # The web shell spawns this instead of `uv run tetclipper` (no uv in the image).
        "TETCLIPPER_CLI": "python -m tetclipper_pipeline.cli",
        "TETCLIPPER_STUDIO_DIST": "/root/studio-dist",
        # Its own address: pinged while a job runs so Modal doesn't scale it down.
        "TETCLIPPER_PUBLIC_URL": PUBLIC_URL,
        # uv_sync also installs a frozen copy of the package into site-packages;
        # the live mount at /root must win, for the server and its CLI subprocesses.
        "PYTHONPATH": "/root",
        "PYTHONUNBUFFERED": "1",
        # Hugging Face's xet transfer keeps log files open on the volume, which
        # blocks volume.reload() in a warm container.
        "HF_HUB_DISABLE_XET": "1",
    })
    .add_local_dir(str(HERE / "tetclipper_pipeline"), remote_path="/root/tetclipper_pipeline", ignore=["**/__pycache__/**"])
    .add_local_dir(str(REPO / "studio" / "editor" / "dist"), remote_path="/root/studio-dist")
)


# Remotion render box: node 22 + Chromium (headless shell) + the studio
# workspace, with the composition pre-bundled at build time.
CHROME_DEPS = [
    "libnss3", "libdbus-1-3", "libatk1.0-0", "libgbm-dev", "libasound2", "libxrandr2",
    "libxkbcommon-dev", "libxfixes3", "libxcomposite1", "libxdamage1", "libatk-bridge2.0-0",
    "libpango-1.0-0", "libcairo2", "libcups2", "fonts-noto-color-emoji", "fonts-noto-core",
]
render_image = (
    modal.Image.from_registry("node:22-bookworm-slim", add_python="3.12")
    .apt_install(*CHROME_DEPS, "ffmpeg")
    .add_local_dir(
        str(REPO / "studio"), remote_path="/root/studio", copy=True,
        ignore=["**/node_modules/**", "**/dist/**", "**/public/**", "**/out/**", "editor/src/**"],
    )
    .run_commands(
        "cd /root/studio && npm ci --no-audit --no-fund",
        "cd /root/studio/composition && npx remotion browser ensure",
        "cd /root/studio/composition && node scripts/bundle.mjs /root/bundle",
    )
    .pip_install("numpy")  # the music mix (cloud/remote.py)
    .env({"TETCLIPPER_BUNDLE": "/root/bundle", "PYTHONPATH": "/root"})
    .add_local_dir(str(HERE / "tetclipper_pipeline"), remote_path="/root/tetclipper_pipeline", ignore=["**/__pycache__/**"])
)


def _mark_deps_synced() -> None:
    """The CLI syncs its uv groups on first run; the image already has them."""
    for marker in (".pipeline_deps_synced", ".net_deps_synced"):
        Path(HOME, marker).touch()


def _commit_forever(every: float = 30.0) -> None:
    """Persist volume writes while the container lives (not just on exit)."""
    while True:
        threading.Event().wait(every)
        try:
            volume.commit()
        except Exception:  # noqa: BLE001 — a failed commit is retried next tick
            pass


@app.function(
    image=image,
    gpu=GPU,
    volumes={HOME: volume},
    # tetclipper-supabase turns on the online sign-in: TETCLIPPER_AUTH=supabase,
    # SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, TETCLIPPER_ADMINS,
    # TETCLIPPER_CORS_ORIGINS, TETCLIPPER_MEDIA_SECRET.
    secrets=[modal.Secret.from_name("tetclipper-web"), modal.Secret.from_name("tetclipper-supabase")],
    timeout=60 * 60,
    scaledown_window=SCALEDOWN,
    max_containers=4,
    cpu=8.0,
    memory=16384,
)
@modal.concurrent(max_inputs=40)
@modal.asgi_app()
def web():
    import sys

    os.chdir("/root")
    if sys.path[0] != "/root":
        sys.path.insert(0, "/root")
    _mark_deps_synced()
    threading.Thread(target=_commit_forever, daemon=True).start()
    from tetclipper_pipeline.server.app import app as fastapi_app

    return fastapi_app


def _in_root() -> None:
    import sys

    os.chdir("/root")
    if sys.path[0] != "/root":
        sys.path.insert(0, "/root")


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, timeout=60 * 60, cpu=8.0, memory=16384)
def analyze(row: dict, start: float | None, end: float | None, captions: str | None = None,
            stages: list[str] | None = None):
    """Studio range job → clip spec, or analysis stages for `find` (generator of progress events)."""
    _in_root()
    _mark_deps_synced()
    volume.reload()
    from tetclipper_pipeline.cloud import remote

    try:
        yield from remote.analyze(row, start, end, captions, stages)
    finally:
        volume.commit()


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, timeout=40 * 60, cpu=8.0, memory=16384)
def matte(job_id: str, clip: int, spec: dict):
    """Cut the speaker out of one clip (generator of progress events)."""
    _in_root()
    _mark_deps_synced()
    volume.reload()
    from tetclipper_pipeline.cloud import remote

    try:
        yield from remote.matte(job_id, clip, spec)
    finally:
        volume.commit()


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, timeout=10 * 60, cpu=4.0, memory=8192)
def second_listen(job_id: str, request: dict) -> list:
    """Swahili second listen over doubtful caption spans ({words, spans, hotwords?, model?})."""
    _in_root()
    _mark_deps_synced()
    try:
        volume.reload()
    except RuntimeError:  # a model download in this container still holds files open; our view is current
        pass
    from tetclipper_pipeline.cloud import remote

    return remote.second_listen(job_id, request)


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, timeout=60 * 60, cpu=8.0, memory=16384)
def asr_bench(segments: list, models: list, modes: list, hotwords: str = "", prompt: str | None = None) -> list:
    """The ears test (asr/bench.py): candidate speech models over audio the user checked.
    Converted models stay on the volume (models/ct2) for the next run."""
    _in_root()
    _mark_deps_synced()
    try:
        volume.reload()
    except RuntimeError:
        pass
    from tetclipper_pipeline.asr import bench

    try:
        return bench.run(segments, models, modes, hotwords, prompt)
    finally:
        volume.commit()


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, timeout=20 * 60, cpu=8.0, memory=8192)
def build_spec(job_id: str, clip: int, captions: str | None = None, glossary: dict | None = None) -> dict:
    """Smart camera + spec for one found moment (mapped across clips by `find`)."""
    _in_root()
    _mark_deps_synced()
    volume.reload()
    from tetclipper_pipeline.cloud import remote

    try:
        return remote.build_spec(job_id, clip, captions, glossary)
    finally:
        volume.commit()


@app.function(image=render_image, volumes={HOME: volume}, timeout=15 * 60, cpu=8.0, memory=8192)
def render_chunk(job_dir: str, clip: int, first: int, last: int) -> bytes:
    """One silent chunk of a clip render (fanned out by `render`)."""
    _in_root()
    volume.reload()
    from tetclipper_pipeline.cloud import remote

    return remote.render_chunk(job_dir, clip, first, last)


@app.function(image=render_image, volumes={HOME: volume}, timeout=30 * 60, cpu=4.0, memory=8192)
def render(job_dir: str, clip: int):
    """Remotion-render one clip spec in parallel chunks (generator of progress events)."""
    _in_root()
    volume.reload()
    from tetclipper_pipeline.cloud import remote

    try:
        yield from remote.render(job_dir, clip, lambda args: render_chunk.starmap(args))
    finally:
        volume.commit()
