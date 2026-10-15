"""tetclipper on Modal: the web shell + pipeline in one GPU container.

    modal secret create tetclipper-web TETCLIPPER_WEB_TOKEN=<random>
    modal deploy pipeline/modal_app.py        # prints the https URL

Everything mutable (models, jobs, clips, secrets.json, llm-cache) lives on
the `tetclipper-home` Volume, mounted as TETCLIPPER_HOME. The browser UI is
the built app/dist, served by the same FastAPI app as the API, so one URL
and one cookie cover both.

The container stays up while a browser tab is open (its SSE stream is an
open request) plus SCALEDOWN seconds, and jobs checkpoint after every stage,
so a job cut off by a scale-down resumes from where it stopped.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import modal

HERE = Path(__file__).resolve().parent  # pipeline/
REPO = HERE.parent
HOME = "/data"
GPU = os.environ.get("TETCLIPPER_MODAL_GPU", "T4")
SCALEDOWN = 15 * 60

app = modal.App("tetclipper")
volume = modal.Volume.from_name("tetclipper-home", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.12")
    # Debian's ffmpeg is built with libass → caption burning works out of the box.
    .apt_install("ffmpeg", "git", "libglib2.0-0", "libsndfile1")
    .uv_sync(uv_project_dir=str(HERE), groups=["pipeline", "server"], extras=[], frozen=True)
    .env({
        "TETCLIPPER_HOME": HOME,
        "TETCLIPPER_DEVICE": "cuda",
        # Debian's ffmpeg carries the NVENC encoder; the renderer probes it and
        # falls back to libx264 (which is why cpu= below is generous).
        "TETCLIPPER_VCODEC": "h264_nvenc",
        # Hybrid: the GPU box analyses and directs; your own machine renders
        # (`tetclipper pull <job> --render`). Drop this to render here too.
        "TETCLIPPER_SKIP_STAGES": "render",
        # The web shell spawns this instead of `uv run tetclipper` (no uv in the image).
        "TETCLIPPER_CLI": "python -m tetclipper_pipeline.cli",
        "TETCLIPPER_DIST": "/root/app/dist",
        # uv_sync also installs a frozen copy of the package into site-packages;
        # the live mount at /root must win, for the server and its CLI subprocesses.
        "PYTHONPATH": "/root",
        "PYTHONUNBUFFERED": "1",
    })
    .add_local_dir(str(HERE / "tetclipper_pipeline"), remote_path="/root/tetclipper_pipeline")
    .add_local_dir(str(REPO / "app" / "dist"), remote_path="/root/app/dist")
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
    secrets=[modal.Secret.from_name("tetclipper-web")],
    timeout=60 * 60,
    scaledown_window=SCALEDOWN,
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
