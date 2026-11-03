"""The online editor's light preview copy: what makes playback possible on a slow
connection is a keyframe every second at a low bitrate, in step with the original."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tetclipper_pipeline.spec import preview


@pytest.fixture
def media(tmp_path):
    from tetclipper_pipeline.render.ffmpeg_bin import available, resolve

    if not available():
        pytest.skip("no ffmpeg")
    resolve()
    # Like the originals that caused the trouble: 1080p with sparse keyframes.
    path = tmp_path / "media.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=12",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "250", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   check=True)
    return path


def _probe(path: Path, *args: str) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", *args, "-of", "json", str(path)],
                                     capture_output=True, text=True, check=True).stdout)


def test_the_copy_is_small_with_a_keyframe_every_second(media):
    out = media.with_name(preview.NAME)
    preview.make(media, out, 1920, 1080)
    assert not out.with_name("preview.part.mp4").exists()

    info = _probe(out, "-show_entries", "stream=codec_type,width,height,duration:format=bit_rate")
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (854, 480)
    assert abs(float(video["duration"]) - 12) < 0.1 and abs(float(audio["duration"]) - 12) < 0.1
    assert int(info["format"]["bit_rate"]) < 1_100_000

    frames = _probe(out, "-select_streams", "v", "-skip_frame", "nokey", "-show_entries", "frame=pts_time")["frames"]
    times = [float(f["pts_time"]) for f in frames]
    assert times[0] == 0 and max(b - a for a, b in zip(times, times[1:])) <= 1.01


def test_a_failed_copy_leaves_nothing_behind(tmp_path):
    from tetclipper_pipeline.render.ffmpeg_bin import available

    if not available():
        pytest.skip("no ffmpeg")
    (tmp_path / "broken.mp4").write_bytes(b"not a video")
    with pytest.raises(RuntimeError):
        preview.make(tmp_path / "broken.mp4", tmp_path / preview.NAME, 1920, 1080)
    assert not list(tmp_path.glob("preview*"))
