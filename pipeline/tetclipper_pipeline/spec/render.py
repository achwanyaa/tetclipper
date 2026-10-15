"""Render a clip spec to mp4 with Remotion (studio/composition/scripts/render.mjs).

On Modal's 16-CPU render function when cloud mode is available (see
cloud/client.py), otherwise on this PC (needs node + `npm install` in studio/).
TETCLIPPER_RENDER=local|cloud forces one. Output: jobs/<id>/studio/clip_NN/
render.mp4 plus a render.json recording which spec version it came from.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import store

STUDIO_DIR = Path(os.environ.get("TETCLIPPER_STUDIO") or Path(__file__).resolve().parents[3] / "studio")
RENDER_SCRIPT = STUDIO_DIR / "composition" / "scripts" / "render.mjs"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def use_cloud() -> bool:
    mode = os.environ.get("TETCLIPPER_RENDER", "")
    if mode in ("local", "cloud"):
        return mode == "cloud"
    from ..cloud import client

    return client.available()


def render(job_dir: Path, clip_idx: int, emit=lambda f, m: None, cloud: bool | None = None) -> Path:
    job_dir = Path(job_dir)
    if not store.spec_path(job_dir, clip_idx).exists():
        raise ValueError(f"clip {clip_idx} has no spec yet")
    versions = store.history(job_dir, clip_idx)
    t0 = time.time()
    if use_cloud() if cloud is None else cloud:
        from ..cloud import client

        out = client.render(job_dir, clip_idx, lambda st, f, m: emit(f, m))
        where = "cloud"
    else:
        out = _render_local(job_dir, clip_idx, emit)
        where = "local"
    (out.parent / "render.json").write_text(json.dumps({
        "output": str(out),
        "spec_version": versions[-1]["version"] if versions else None,
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "where": where,
        "seconds": round(time.time() - t0, 1),
    }, indent=1), encoding="utf-8")
    return out


def _render_local(job_dir: Path, clip_idx: int, emit) -> Path:
    spec_file = store.spec_path(job_dir, clip_idx)
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Rendering needs Node.js (node) on PATH.")
    if not (STUDIO_DIR / "node_modules").exists():
        raise RuntimeError(f"Run `npm install` in {STUDIO_DIR} first.")
    out = store.clip_dir(job_dir, clip_idx) / "render.mp4"
    tmp = out.with_suffix(".part.mp4")
    child = subprocess.Popen(
        [node, str(RENDER_SCRIPT), str(spec_file), str(job_dir), str(tmp)],
        cwd=str(STUDIO_DIR / "composition"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    result: dict = {}
    assert child.stdout is not None
    for line in child.stdout:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "progress":
            emit(float(event.get("fraction", -1)), event.get("message", ""))
        elif event.get("event") == "result":
            result = event
    stderr = child.stderr.read() if child.stderr else ""
    code = child.wait()
    if code != 0 or not result.get("ok"):
        raise RuntimeError(result.get("error") or stderr.strip()[-600:] or f"render exited {code}")
    tmp.replace(out)
    return out
