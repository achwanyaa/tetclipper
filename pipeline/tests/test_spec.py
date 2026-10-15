"""Clip spec: schema validation, camera path → keyframes, store + undo, transcript."""

import json

import pytest

from tetclipper_pipeline.camera import director
from tetclipper_pipeline.spec import build, store, transcript
from tetclipper_pipeline.spec.schema import validate


def _spec(**over):
    spec = {
        "version": 1,
        "source": {"src": "media.mp4", "start": 5.0, "end": 20.0, "width": 1920, "height": 1080},
        "intro": None,
        "cuts": [],
        "words": [
            {"text": "Hello", "start": 5.2, "end": 5.6, "speaker": "S0"},
            {"text": "world.", "start": 5.7, "end": 6.1, "speaker": "S0", "emphasis": True},
            {"text": "Next", "start": 7.5, "end": 7.9, "speaker": "S1"},
        ],
        "captions": {"enabled": True, "style": "hormozi"},
        "crop": {"keyframes": []},
        "effects": [],
        "progressBar": {"enabled": False, "color": "#FFD700"},
    }
    spec.update(over)
    return spec


def test_valid_spec_passes():
    assert validate(_spec()) == []


def test_intro_and_effects_validate():
    spec = _spec(
        intro={"src": "assets/intro.jpg", "duration": 2},
        effects=[{"type": "punch-in", "at": 6, "duration": 2, "amount": 1.12}, {"type": "flash", "at": 8, "duration": 0.3}],
        cuts=[{"start": 9, "end": 10}],
    )
    assert validate(spec) == []


@pytest.mark.parametrize(
    "patch, needle",
    [
        ({"captions": {"style": "comic-sans"}}, "captions.style"),
        ({"intro": {"src": "x.jpg", "duration": 9}}, "intro"),
        ({"effects": [{"type": "punch-in", "at": 1}]}, "duration"),
        ({"effects": [{"type": "wobble", "at": 1, "duration": 1}]}, "effects[0]"),
        ({"bogus": 1}, "unknown field"),
        ({"source": {"src": "m.mp4", "start": 10, "end": 5}}, "end must be after start"),
    ],
)
def test_invalid_specs_are_reported(patch, needle):
    problems = validate(_spec(**patch))
    assert problems and any(needle in p for p in problems), problems


def _trajectory(n=100, fps=25, cut_at=50, punch_start=1.0):
    # speaker A centred at x=600 for frames < cut_at, speaker B at x=1300 after
    src_h = 1080
    base_w = src_h * 9 / 16
    punches = [director.Punch(start=punch_start, trigger="laugh")]
    env = director.punch_envelope(n, fps, punches)
    frames = []
    for f in range(n):
        cx = 600 if f < cut_at else 1300
        w, h = base_w / env[f], src_h / env[f]
        frames.append([cx - w / 2, (src_h - h) / 2, w, h])
    return {
        "fps": fps,
        "frames": frames,
        "cuts": [cut_at],
        "punches": [{"start": punch_start, "end": punches[0].end, "trigger": "laugh"}],
    }


def test_keyframes_from_trajectory_splits_punches_and_keeps_cuts():
    keyframes, effects = build.keyframes_from_trajectory(_trajectory(), 1920, 1080, clip_start=10.0)
    # a static two-shot path collapses to a handful of keyframes
    assert 2 <= len(keyframes) <= 6
    # the punch zoom was divided back out of the camera path
    assert all(abs(k["zoom"] - 1.0) < 0.01 for k in keyframes)
    # the hard cut is kept as a jump
    cut_kfs = [k for k in keyframes if k.get("cut")]
    assert len(cut_kfs) == 1 and cut_kfs[0]["t"] == pytest.approx(12.0)
    assert cut_kfs[0]["x"] == pytest.approx(1300 / 1920, abs=1e-3)
    # punch-in becomes an editable effect in source time
    assert effects == [{"type": "punch-in", "at": 11.0, "duration": pytest.approx(2.1), "amount": director.PUNCH_ZOOM}]
    assert validate(_spec(crop={"keyframes": keyframes}, effects=effects)) == []


def test_store_save_undo_and_sync(tmp_path):
    job = tmp_path
    store.save(job, 0, _spec(), reason="built")
    store.save(job, 0, _spec(captions={"enabled": True, "style": "beast"}), reason="style")
    assert store.load(job, 0)["captions"]["style"] == "beast"
    assert [h["reason"] for h in store.history(job, 0)] == ["built", "style"]

    restored = store.undo(job, 0)
    assert restored["captions"]["style"] == "hormozi"
    assert store.undo(job, 0) is None  # only one version left

    # a direct edit (Claude Code) that breaks the schema is rolled back
    path = store.spec_path(job, 0)
    bad = json.loads(path.read_text())
    bad["captions"]["style"] = "nope"
    path.write_text(json.dumps(bad))
    spec, problems = store.sync_from_disk(job, 0)
    assert problems and spec["captions"]["style"] == "hormozi"
    assert json.loads(path.read_text())["captions"]["style"] == "hormozi"

    # a valid direct edit is recorded
    good = json.loads(path.read_text())
    good["intro"] = {"src": "assets/intro.jpg", "duration": 1.5}
    path.write_text(json.dumps(good))
    spec, problems = store.sync_from_disk(job, 0, reason="claude: intro")
    assert not problems and spec["intro"]["duration"] == 1.5
    assert store.history(job, 0)[-1]["reason"] == "claude: intro"
    assert store.list_clips(job) == [0]


def test_transcript_lists_phrases_with_word_indices(tmp_path):
    spec = _spec(cuts=[{"start": 7.0, "end": 8.0}])
    spec["words"][0]["hidden"] = True
    text = transcript.render(tmp_path, spec)
    assert "[5.20–6.10] S0 #0-1: ~~Hello~~ world." in text
    assert "#2-2 ✂: Next" in text
