"""A light copy of a job's video for the online editor's preview only (renders
always use the original).

Originals often have a keyframe only every 8 s at 3+ Mbps. Every cut starts a new
video element in the player, which can't show a frame until it has fetched back to
the last keyframe, so on a slow connection the picture and sound never catch up.
A keyframe every second at under 1 Mbps fixes that, and costs a quarter of the
data charges too."""

from __future__ import annotations

import subprocess
from pathlib import Path

NAME = "preview.mp4"
SHORT_SIDE = 480


def make(media: Path, out: Path, width: int, height: int) -> None:
    from ..render import ffmpeg_bin

    size = f"-2:{min(SHORT_SIDE, height)}" if width >= height else f"{min(SHORT_SIDE, width)}:-2"
    part = out.with_name(f"{out.stem}.part.mp4")
    run = subprocess.run(
        [ffmpeg_bin.ffmpeg(), "-y", "-loglevel", "error", "-i", str(media),
         "-vf", f"fps=30,scale={size}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
         "-maxrate", "700k", "-bufsize", "700k", "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", "-b:a", "64k", "-movflags", "+faststart", str(part)],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(run.stderr[-400:])
    part.replace(out)
