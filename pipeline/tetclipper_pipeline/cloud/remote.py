"""The work done inside Modal functions. Each entry point is a generator of
progress events ({"event": "progress", stage, fraction, message}) ending in
one {"event": "result", ...}, which modal_app.py relays to the PC."""

from __future__ import annotations

import json
import os
import queue as queue_mod
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterator

STUDIO_DIR = Path("/root/studio")


def _threaded(work: Callable[[Callable[[str, float, str], None]], dict]) -> Iterator[dict]:
    """Run `work(emit)` on a thread and yield its progress as it happens."""
    events: queue_mod.Queue = queue_mod.Queue()

    def emit(stage: str, fraction: float, message: str) -> None:
        events.put({"event": "progress", "stage": stage, "fraction": fraction, "message": message})

    def run() -> None:
        try:
            events.put({"event": "result", "ok": True, **work(emit)})
        except Exception as err:  # noqa: BLE001 — every failure goes back to the PC
            events.put({"event": "result", "ok": False, "error": str(err)})

    threading.Thread(target=run, daemon=True).start()
    while True:
        ev = events.get()
        yield ev
        if ev["event"] == "result":
            return


def analyze(row: dict, start: float, end: float, captions: str | None) -> Iterator[dict]:
    """ASR → diarize → events → camera → spec for a range job whose ingest
    (media.mp4, audio16k.wav, ingest.json) the PC already uploaded."""

    def work(emit) -> dict:
        from .. import cli
        from ..edits import manual
        from ..jobs import queue
        from ..spec import build as spec_build
        from ..spec import store as spec_store

        queue.import_job(row["id"], row["source_type"], row["source"], row["settings_json"], row.get("title"))
        job = queue.get_job(row["id"])
        stages = [s for s in cli._stages() if s.name in ("ingest", "asr", "diarize", "events")]  # noqa: SLF001
        results = queue.run_stages(job, stages, emit)
        offset = float(results["ingest"].get("section_offset", 0.0))
        job = queue.get_job(row["id"]) or job
        clips = spec_store.list_clips(job.dir)
        if clips:
            idx = clips[0]
        else:
            idx = manual.add_range(job, start - offset, end - offset, lambda f, m: emit("spec", f, m),
                                   caption_preset=captions, render=False)["clip_index"]
        spec_build.build(job.dir, idx, style=captions, emit=lambda f, m: emit("spec", f, m))
        queue.set_job_status(job.id, "done", None)
        return {"job_id": job.id, "clip": idx}

    return _threaded(work)


def render(job_dir: str, clip: int) -> Iterator[dict]:
    """Remotion-render studio/clip_NN/spec.json to studio/clip_NN/render.mp4."""
    clip_dir = Path(job_dir) / "studio" / f"clip_{clip:02d}"
    tmp = clip_dir / "render.part.mp4"
    concurrency = os.environ.get("TETCLIPPER_RENDER_CONCURRENCY", "16")
    yield {"event": "progress", "stage": "render", "fraction": 0.01, "message": f"Renderer up ({concurrency} workers)…"}
    child = subprocess.Popen(
        # Node sees the host's cores, not the container's: pass the real budget.
        ["node", str(STUDIO_DIR / "composition" / "scripts" / "render.mjs"), str(clip_dir / "spec.json"), job_dir, str(tmp),
         f"--concurrency={concurrency}"],
        cwd=str(STUDIO_DIR / "composition"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    result: dict = {}
    assert child.stdout is not None
    for line in child.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("event") == "progress":
            yield ev
        elif ev.get("event") == "result":
            result = ev
    err = child.stderr.read() if child.stderr else ""
    if child.wait() != 0 or not result.get("ok"):
        yield {"event": "result", "ok": False, "error": result.get("error") or err[-800:] or "render failed"}
        return
    tmp.replace(clip_dir / "render.mp4")
    yield {"event": "result", "ok": True, "output": f"studio/clip_{clip:02d}/render.mp4"}
