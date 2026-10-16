"""Cut the speaker out of a clip's source range: studio/clip_NN/fg.webm.

A transparent VP9 video (alpha) of just the person, in the source's own
geometry and timing (from `start`), so the composition can place it with the
same crop as the background and draw behind-the-speaker effects in between.

Matting model: RobustVideoMatting (Lin et al., GPL-3.0, fetched via torch.hub
at runtime), built for people in video with temporal consistency (no
flicker). Runs on the Modal GPU; on a CPU it works but is slow.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import store

PAD = 0.5  # seconds of matte either side of the range (trim slack)
BATCH = 8


def make(job_dir: Path, clip: int, emit=lambda f, m: None) -> dict:
    import numpy as np
    import torch

    from .. import config
    from ..asr.stage import _point_caches_at_home
    from ..render import ffmpeg_bin

    _point_caches_at_home()  # torch.hub cache under the app's models dir
    job_dir = Path(job_dir)
    spec = store.load(job_dir, clip)
    if spec is None:
        raise ValueError(f"clip {clip} has no spec yet")
    src = spec["source"]
    media = job_dir / src["src"]
    w, h = int(src["width"]), int(src["height"])
    start = max(0.0, float(src["start"]) - PAD)
    end = float(src["end"]) + PAD
    fps = 30

    device = "cuda" if config.compute_device() == "cuda" else "cpu"
    emit(-1, "Loading the matting model…")
    model = torch.hub.load("PeterL1n/RobustVideoMatting", "mobilenetv3", trust_repo=True).eval().to(device)
    ffmpeg = ffmpeg_bin.ffmpeg()
    out = store.clip_dir(job_dir, clip) / "fg.webm"
    part = out.with_suffix(".part.webm")

    decode = subprocess.Popen(
        [ffmpeg, "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(media),
         "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    encode = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps),
         "-i", "-", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "32",
         "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-auto-alt-ref", "0", str(part)],
        stdin=subprocess.PIPE,
    )
    assert decode.stdout is not None and encode.stdin is not None
    frame_bytes = w * h * 3
    total = int((end - start) * fps)
    rec = [None] * 4
    done = 0
    ratio = 0.25 if max(w, h) >= 1280 else 0.4
    with torch.no_grad():
        while True:
            batch = []
            for _ in range(BATCH):
                buf = decode.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                batch.append(np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3))
            if not batch:
                break
            x = torch.from_numpy(np.stack(batch)).to(device).permute(0, 3, 1, 2).float().div(255).unsqueeze(0)
            _fgr, pha, *rec = model(x, *rec, ratio)
            alpha = (pha[0, :, 0].clamp(0, 1).mul(255).byte().cpu().numpy())
            for rgb, a in zip(batch, alpha):
                encode.stdin.write(np.dstack([rgb, a]).tobytes())  # original colours + matte
            done += len(batch)
            if done % (BATCH * 15) < BATCH:
                emit(min(0.99, done / max(1, total)), f"Cutting out the speaker… {done}/{total} frames")
    encode.stdin.close()
    decode.wait()
    if encode.wait() != 0 or done == 0:
        raise RuntimeError("matte encode failed")
    part.replace(out)
    return {"src": out.relative_to(job_dir).as_posix(), "start": round(start, 3), "frames": done}


def attach(job_dir: Path, clip: int, matte: dict) -> dict:
    """Record the matte in the clip's spec (one history step)."""
    spec = store.load(job_dir, clip)
    spec = {**spec, "matte": {"src": matte["src"], "start": matte["start"]}}
    return store.save(job_dir, clip, spec, reason="speaker cut out (behind-the-speaker effects on)")
