"""One-off timing probe for the hosted renderer: `modal run pipeline/modal_diag.py`.
Runs inside the same image/volume as modal_app.web and prints how long each
piece of a clip render takes, so a slow render can be pinned on decode,
filters, or the encoder."""
from __future__ import annotations

import subprocess
import time

import modal

from modal_app import HOME, GPU, image, volume

app = modal.App("tetclipper-diag")

JOB = f"{HOME}/jobs/20261013-102003-3107ec"
SRC = f"{JOB}/media.mp4"
ASS = f"{JOB}/clips/clip_00.ass"
FONTS = "/root/tetclipper_pipeline/captions/fonts"
VF = f"crop=w=606:h=1080:x=694:y=0,scale=1080:1920:flags=lanczos,setsar=1,subtitles=filename='{ASS}':fontsdir='{FONTS}'"


def run(label: str, args: list[str], timeout: int = 300) -> None:
    t0 = time.time()
    try:
        p = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, timeout=timeout)
        status = "ok" if p.returncode == 0 else f"rc={p.returncode} {p.stderr[-300:]}"
    except subprocess.TimeoutExpired:
        status = f"TIMEOUT >{timeout}s"
    print(f"{label:<34} {time.time() - t0:7.1f}s  {status}", flush=True)


@app.function(image=image, gpu=GPU, volumes={HOME: volume}, cpu=8.0, memory=16384, timeout=1800)
def probe() -> None:
    import os

    print("nproc:", os.cpu_count(), "| media size:", os.path.getsize(SRC) // 1_000_000, "MB", flush=True)
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate", "-of", "csv=p=0", SRC],
                       capture_output=True, text=True)
    print("source stream:", p.stdout.strip(), flush=True)
    run("read 200MB (volume)", ["-i", SRC, "-t", "0.1", "-f", "null", "-"], 120)
    run("decode 10s @1555s", ["-ss", "1555", "-t", "10", "-i", SRC, "-f", "null", "-"])
    run("decode+crop+scale 10s", ["-ss", "1555", "-t", "10", "-i", SRC, "-vf", VF.split(",subtitles")[0], "-f", "null", "-"])
    run("full filters, no encode 10s", ["-ss", "1555", "-t", "10", "-i", SRC, "-vf", VF, "-f", "null", "-"])
    run("full + libx264 ultrafast 10s", ["-ss", "1555", "-t", "10", "-i", SRC, "-vf", VF, "-c:v", "libx264", "-preset", "ultrafast", "-an", "/tmp/a.mp4"])
    run("full + libx264 medium 10s", ["-ss", "1555", "-t", "10", "-i", SRC, "-vf", VF, "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-an", "/tmp/b.mp4"])
    run("nvenc probe (black 0.2s)", ["-f", "lavfi", "-i", "color=black:s=320x240:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"], 60)
    run("full + h264_nvenc 10s", ["-ss", "1555", "-t", "10", "-i", SRC, "-vf", VF, "-c:v", "h264_nvenc", "-preset", "p5", "-an", "/tmp/c.mp4"])


@app.local_entrypoint()
def main() -> None:
    probe.remote()
