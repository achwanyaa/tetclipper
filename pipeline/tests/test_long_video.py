"""Full-length videos: which frames need Remotion, and the render that overlays
them on one ffmpeg encode. Transition numbers are reference values from
studio/composition/src/timeline.ts buildTimeline()."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tetclipper_pipeline.cloud import remote
from tetclipper_pipeline.spec.long_video import cut_transitions, overlay_filter, remotion_ranges
from tetclipper_pipeline.spec.schema import validate
from tetclipper_pipeline.spec.timeline import total_frames

FADE = {"type": "fade", "duration": 0.5}


def _spec(**fields) -> dict:
    return {
        "version": 1, "format": "landscape",
        "source": {"src": "media.mp4", "start": 0, "end": 3600, "width": 1920, "height": 1080},
        "captions": {"enabled": False}, "crop": {"keyframes": []}, "words": [{"text": "hi", "start": 1, "end": 2}],
        **fields,
    }


def test_the_format_field_validates():
    assert validate(_spec()) == []
    assert validate(_spec(format="square"))


def test_cut_transitions_match_the_composition():
    spec = {"source": {"start": 5, "end": 12}, "cuts": [
        {"start": 7, "end": 8, "transition": FADE}, {"start": 7.5, "end": 9},
        {"start": 11, "end": 11.1, "transition": {"type": "wipe", "duration": 2}},
    ]}
    assert cut_transitions(spec) == [(53, 14), (107, 26)]


def test_a_plain_video_needs_no_remotion():
    assert remotion_ranges(_spec()) == []


def test_only_frames_with_something_extra_need_remotion():
    spec = _spec(
        intro={"src": "i.jpg", "duration": 2},
        outro={"src": "o.jpg", "duration": 3, "transition": FADE},
        cuts=[{"start": 100, "end": 110, "transition": {"type": "fade", "duration": 1}}, {"start": 200, "end": 201}],
        effects=[{"type": "glass-text", "at": 50, "duration": 4, "text": "John 3:16"}],
    )
    total = total_frames(spec)
    assert total == 60 + (3600 - 11) * 30 + 90 - 15
    assert remotion_ranges(spec) == [
        (0, 59),  # intro
        (60 + 1500 - 1, 60 + 1620 + 1),  # the verse, with a frame of margin each side
        (60 + 3000 - 15, 60 + 3000 + 14),  # the transition, centred on its cut
        (total - 90, total - 1),  # outro
    ]


def test_an_effect_in_a_cut_needs_no_frames():
    assert remotion_ranges(_spec(cuts=[{"start": 40, "end": 60}], effects=[{"type": "flash", "at": 50, "duration": 1}])) == []


@pytest.mark.parametrize("fields", [
    {"captions": {"enabled": True}},
    {"progressBar": {"enabled": True}},
    {"crop": {"keyframes": [{"t": 1, "x": 0.5, "y": 0.5, "zoom": 1.2}]}},
])
def test_these_need_every_frame(fields):
    spec = _spec(**fields)
    assert remotion_ranges(spec) == [(0, total_frames(spec) - 1)]


def test_overlay_timing_puts_each_joined_frame_on_its_own_output_frame():
    timing, enable = overlay_filter([(10, 19), (50, 54)])
    assert timing == "setpts='(N+10+gte(N,10)*30)/30/TB',format=yuv420p"
    assert enable == "between(t,0.31667,0.65000)+between(t,1.65000,1.81667)"


@pytest.fixture
def media(tmp_path):
    from tetclipper_pipeline.render.ffmpeg_bin import available, resolve

    if not available():
        pytest.skip("no ffmpeg")
    resolve()
    # A clock for a picture and a beep at exactly 2 s.
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "gradients=s=1920x1080:r=30:d=6:speed=0.5",
                    "-f", "lavfi", "-i", "sine=frequency=800:sample_rate=48000:duration=6",
                    "-af", "volume='if(between(t,2,2.2),1,0)':eval=frame", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp_path / "media.mp4")], check=True)
    return tmp_path


def _frame_rgb(path: Path, frame: int) -> tuple[float, float, float]:
    np = pytest.importorskip("numpy")
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"select='eq(n,{frame})',scale=16:9",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).mean(axis=0).tolist())


def _red_chunks(items):
    """Stands in for Remotion: every frame it renders is solid red."""
    import tempfile

    for _, _, first, last in items:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "c.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=1920x1080:r=30",
                            "-frames:v", str(last - first + 1), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True)
            yield out.read_bytes()


def _is_red(rgb) -> bool:
    return rgb[0] > 150 and rgb[1] < 90 and rgb[2] < 90


def test_the_render_overlays_effects_on_exactly_their_frames(media):
    pytest.importorskip("numpy")
    clip = media / "studio" / "clip_00"
    clip.mkdir(parents=True)
    spec = _spec(
        source={"src": "media.mp4", "start": 0, "end": 6, "width": 1920, "height": 1080},
        cuts=[{"start": 1, "end": 1.5}],
        effects=[{"type": "flash", "at": 3, "duration": 0.5}, {"type": "flash", "at": 5, "duration": 0.2}],
        words=[],
    )
    (clip / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    ranges = remotion_ranges(spec)
    assert len(ranges) == 2

    events = list(remote.render(str(media), 0, _red_chunks))
    result = events[-1]
    assert result["ok"], result
    assert result["remotion_frames"] == sum(b - a + 1 for a, b in ranges)

    out = clip / "render.mp4"
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                       "stream=codec_type,nb_read_frames,duration,width,height", "-of", "json", str(out)],
                                      capture_output=True, text=True, check=True).stdout)["streams"]
    video = next(s for s in probe if s["codec_type"] == "video")
    audio = next(s for s in probe if s["codec_type"] == "audio")
    assert int(video["nb_read_frames"]) == total_frames(spec) == 165
    assert (video["width"], video["height"]) == (1920, 1080)
    assert abs(float(audio["duration"]) - 5.5) < 0.05

    for a, b in ranges:
        assert _is_red(_frame_rgb(out, a)) and _is_red(_frame_rgb(out, b))
        assert not _is_red(_frame_rgb(out, a - 1)) and not _is_red(_frame_rgb(out, b + 1))
    assert not _is_red(_frame_rgb(out, 20))


def test_the_sound_stays_in_time_after_a_cut(media):
    np = pytest.importorskip("numpy")
    spec = _spec(source={"src": "media.mp4", "start": 0, "end": 6, "width": 1920, "height": 1080}, cuts=[{"start": 1, "end": 1.5}], words=[])
    wav = media / "speech.wav"
    remote._exact_speech(spec, media / "media.mp4", wav, media, total_frames(spec))  # noqa: SLF001
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "48000", "-"],
                         capture_output=True, check=True).stdout
    data = np.frombuffer(raw, dtype=np.float32)
    assert abs(len(data) - 5.5 * 48000) < 2
    # The beep at 2 s in the source is at 1.5 s after half a second is cut before it.
    loud = np.flatnonzero(np.abs(data) > 0.02)
    assert abs(loud[0] / 48000 - 1.5) < 0.03
