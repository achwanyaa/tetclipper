"""Intro/outro timing, music ranges and the soundtrack they produce. The numbers
are reference values from studio/composition/src (timeline.ts, music.ts), so the
Python render path and the Remotion preview agree on every frame."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tetclipper_pipeline.spec.schema import validate
from tetclipper_pipeline.spec.timeline import (
    intro_on_screen,
    outro_start,
    segments,
    source_time_at,
    total_frames,
)

BASE = {"source": {"src": "m.mp4", "start": 5, "end": 12}, "cuts": [{"start": 7, "end": 8}]}
WORDS = [
    {"text": "a", "start": 5.2, "end": 5.6}, {"text": "b", "start": 5.8, "end": 6.3},
    {"text": "c", "start": 8.5, "end": 9.0}, {"text": "d", "start": 10.4, "end": 11.1},
]
FADE = {"type": "fade", "duration": 0.5}
WIPE = {"type": "wipe", "duration": 1}
SONG = {"src": "x.mp3", "volume": 0.3, "duck": 0.4, "fadeIn": 0.5, "fadeOut": 1, "offset": 10, "end": 14}


@pytest.mark.parametrize(
    "spec, video_from, on_screen, outro_from, total",
    [
        ({**BASE, "intro": {"src": "i", "duration": 2}, "outro": {"src": "o", "duration": 3}}, 60, 60, 240, 330),
        ({**BASE, "intro": {"src": "i", "duration": 2, "transition": FADE},
          "outro": {"src": "o", "duration": 3, "transition": WIPE}}, 45, 60, 195, 285),
        ({"source": {"src": "m", "start": 5, "end": 5.2},
          "intro": {"src": "i", "duration": 0.5, "transition": {"type": "fade", "duration": 2}},
          "outro": {"src": "o", "duration": 1, "transition": {"type": "fade", "duration": 2}}}, 9, 15, 9, 39),
        ({**BASE, "outro": {"src": "o", "kind": "video", "duration": 1.25}}, 0, 0, 180, 218),
    ],
)
def test_timeline_matches_the_composition(spec, video_from, on_screen, outro_from, total):
    assert segments(spec)[0] == video_from
    assert intro_on_screen(spec) == on_screen
    assert outro_start(spec) == outro_from
    assert total_frames(spec) == total


def test_cut_transitions_leave_the_length_alone():
    plain = {"source": {"src": "m", "start": 5, "end": 12}, "cuts": [{"start": 7, "end": 8}, {"start": 7.5, "end": 9}, {"start": 11, "end": 11.1}]}
    moved = {**plain, "cuts": [{**plain["cuts"][0], "transition": FADE}, plain["cuts"][1], {**plain["cuts"][2], "transition": WIPE}]}
    assert total_frames(plain) == total_frames(moved) == 147


def test_source_time_is_none_once_only_the_outro_is_left():
    spec = {**BASE, "intro": {"src": "i", "duration": 2, "transition": FADE}, "outro": {"src": "o", "duration": 3, "transition": WIPE}}
    video_from, segs = segments(spec)
    at = [source_time_at(video_from, segs, f, has_outro=True) for f in (44, 45, 194, 195, 224, 225, 284)]
    assert at[0] is None and at[-2:] == [None, None]
    assert [round(t, 6) for t in at[1:5]] == [5, 10.966667, 11, 11.966667]
    # Without an outro the last frame still reports the clip's end.
    assert source_time_at(video_from, segs, 999) == 12


@pytest.mark.parametrize(
    "spec, n, picks, total",
    [
        ({**BASE, "words": WORDS, "intro": {"src": "i", "duration": 1}, "music": {**SONG, "loop": False}},
         210, [0, 0.2, 0.12, 0.19, 0, 0, 0, 0, 0, 0], 21.455333),
        ({**BASE, "words": WORDS, "outro": {"src": "o", "kind": "video", "duration": 2, "transition": FADE}, "music": SONG},
         225, [0, 0.08, 0.12, 0.3, 0.3, 0.3, 0.12, 0.12, 0.096, 0], 38.216),
        ({**BASE, "words": WORDS, "intro": {"src": "i", "kind": "video", "duration": 1, "volume": 0},
          "music": {**SONG, "fadeIn": 0, "fadeOut": 0, "offset": 3, "end": 2, "loop": False}},
         210, [0.3, 0.3, 0.12, 0.3, 0.12, 0.12, 0.3, 0.12, 0.3, 0.3], 47.88),
    ],
)
def test_music_gains_match_the_composition(spec, n, picks, total):
    from tetclipper_pipeline.spec.music import frame_gains

    g = frame_gains(spec)
    assert len(g) == n
    assert [round(g[i], 6) for i in (0, 10, 40, 100, 119, 120, 150, 180, 200, n - 1)] == picks
    assert round(sum(g), 6) == total


def _spec(**fields) -> dict:
    return {"version": 1, "source": {"src": "m.mp4", "start": 5, "end": 25}, **fields}


def test_new_fields_validate_and_old_specs_still_do():
    assert validate(_spec(intro={"src": "i.jpg", "duration": 2, "fit": "cover"})) == []
    assert validate(_spec(
        intro={"src": "i.mp4", "kind": "video", "duration": 12, "volume": 0.5, "transition": {"type": "zoom", "duration": 1}},
        outro={"src": "o.jpg", "transition": None},
        music={"src": "x.mp3", "offset": 3, "end": 9},
        cuts=[{"start": 6, "end": 7, "transition": {"type": "blur"}}, {"start": 9, "end": 10}],
    )) == []
    assert validate(_spec(outro={"src": "o.jpg", "duration": 31}))
    assert validate(_spec(cuts=[{"start": 6, "end": 7, "transition": {"type": "spin"}}]))


def test_fit_music_loops_pads_and_trims():
    np = pytest.importorskip("numpy")
    from tetclipper_pipeline.cloud.remote import _fit_music

    pcm = np.arange(6, dtype=np.float32).reshape(3, 2)
    assert _fit_music(pcm, 7, True)[:, 0].tolist() == [0, 2, 4, 0, 2, 4, 0]
    assert _fit_music(pcm, 5, False)[:, 0].tolist() == [0, 2, 4, 0, 0]
    assert _fit_music(pcm, 2, False)[:, 0].tolist() == [0, 2]
    assert len(_fit_music(pcm[:0], 4, True)) == 4


@pytest.fixture
def ffmpeg():
    from tetclipper_pipeline.render.ffmpeg_bin import available, resolve

    if not available():
        pytest.skip("no ffmpeg")
    resolve()  # puts the bundled ffmpeg first on PATH
    return "ffmpeg"


def _run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _tone(path: Path, seconds: float, hz: int) -> None:
    _run("-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000:duration={seconds}", "-ac", "2", str(path))


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def _loudness(path: Path, start: float, length: float) -> float:
    """Peak of a stretch of the file, 0–1."""
    np = pytest.importorskip("numpy")
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(start), "-t", str(length), "-i", str(path),
                          "-f", "f32le", "-ac", "1", "-ar", "48000", "-"], capture_output=True, check=True).stdout
    data = np.frombuffer(raw, dtype=np.float32)
    return float(np.abs(data).max()) if len(data) else 0.0


def test_music_range_is_what_plays_and_it_loops(tmp_path, ffmpeg):
    pytest.importorskip("numpy")
    from tetclipper_pipeline.cloud.remote import _mix_music

    # Silence, then a 1 s tone at 2–3 s, then silence: only the range has sound.
    _run("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8", "-af", "volume='if(between(t,2,3),0.5,0)':eval=frame",
         "-ac", "2", str(tmp_path / "x.wav"))
    _run("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "5", str(tmp_path / "speech.wav"))
    spec = {"source": {"src": "m", "start": 0, "end": 5},
            "music": {"src": "x.wav", "volume": 1, "duck": 1, "fadeIn": 0, "fadeOut": 0, "offset": 2, "end": 3}}
    _mix_music(spec, tmp_path, tmp_path / "speech.wav", tmp_path / "out.wav", 150)
    assert abs(_duration(tmp_path / "out.wav") - 5) < 0.05
    for second in range(5):  # the 1 s range repeats for the whole clip
        assert _loudness(tmp_path / "out.wav", second + 0.2, 0.6) > 0.03

    spec["music"]["loop"] = False
    _mix_music(spec, tmp_path, tmp_path / "speech.wav", tmp_path / "out.wav", 150)
    assert _loudness(tmp_path / "out.wav", 0.2, 0.6) > 0.03
    assert _loudness(tmp_path / "out.wav", 1.5, 3) < 0.003


def test_bookend_sound_lands_where_the_video_does(tmp_path, ffmpeg):
    from tetclipper_pipeline.cloud.remote import _mix_bookends

    _tone(tmp_path / "side.mp4", 2, 660)
    _run("-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=1", "-c:v", "libx264", str(tmp_path / "silent.mp4"))
    _run("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "6", str(tmp_path / "speech.wav"))
    spec = {"source": {"src": "m", "start": 0, "end": 4},
            "outro": {"src": "side.mp4", "kind": "video", "duration": 2, "volume": 1, "transition": None}}
    assert _mix_bookends(spec, tmp_path, tmp_path / "speech.wav", tmp_path / "out.wav")
    assert abs(_duration(tmp_path / "out.wav") - 6) < 0.05
    assert _loudness(tmp_path / "out.wav", 0.5, 3) < 0.01
    assert _loudness(tmp_path / "out.wav", 4.2, 1.5) > 0.05

    # A video with no audio track, or turned down, adds nothing and doesn't fail.
    spec["outro"]["src"] = "silent.mp4"
    assert not _mix_bookends(spec, tmp_path, tmp_path / "speech.wav", tmp_path / "out2.wav")
    spec["outro"].update(src="side.mp4", volume=0)
    assert not _mix_bookends(spec, tmp_path, tmp_path / "speech.wav", tmp_path / "out2.wav")
