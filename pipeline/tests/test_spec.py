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


@pytest.mark.parametrize(
    "source, cuts, intro, frames",
    [
        # reference values from studio/composition/src/timeline.ts buildTimeline()
        ((0, 41.867), [], None, 1256),
        ((0, 41.867), [(6, 7.5)], 2, 1271),
        ((5.017, 125.0), [(10.05, 12.31), (11, 13.017), (50, 50.01)], 1.25, 3548),
        ((3.3, 9.95), [(2, 4), (9, 20)], None, 150),
    ],
)
def test_total_frames_matches_the_composition_timeline(source, cuts, intro, frames):
    from tetclipper_pipeline.cloud.remote import chunk_ranges, total_frames

    spec = {
        "source": {"start": source[0], "end": source[1]},
        "cuts": [{"start": a, "end": b} for a, b in cuts],
        "intro": {"duration": intro} if intro else None,
    }
    assert total_frames(spec) == frames
    ranges = chunk_ranges(frames)
    assert ranges[0][0] == 0 and ranges[-1][1] == frames - 1
    assert all(b + 1 == a for (_, b), (a, _) in zip(ranges, ranges[1:]))


def test_music_gains_match_the_composition():
    from tetclipper_pipeline.spec.music import frame_gains

    spec = {
        "source": {"src": "m.mp4", "start": 5, "end": 12},
        "intro": {"src": "i.jpg", "duration": 1},
        "cuts": [{"start": 7, "end": 8}],
        "words": [
            {"text": "a", "start": 5.2, "end": 5.6}, {"text": "b", "start": 5.8, "end": 6.3},
            {"text": "c", "start": 8.5, "end": 9.0}, {"text": "d", "start": 10.4, "end": 11.1},
        ],
        "music": {"src": "x.mp3", "volume": 0.3, "duck": 0.4, "fadeIn": 0.5, "fadeOut": 1},
    }
    g = frame_gains(spec)
    # reference values from studio/composition/src/music.ts musicGains()
    assert len(g) == 210
    picks = [round(g[i], 6) for i in (0, 10, 31, 40, 45, 60, 100, 150, len(g) - 1)]
    assert picks == [0, 0.2, 0.3, 0.12, 0.12, 0.12, 0.3, 0.3, 0]
    assert round(sum(g), 6) == 41.04
    assert validate({**_spec(), "music": spec["music"]}) == []


# ---------- mixed-language captions: word list + doubts ----------

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _w(text, start, end, **kw):
    return {"text": text, "start": start, "end": end, **kw}


MISHEARD = [
    _w("reading", 12.65, 12.89), _w("this", 12.93, 13.11), _w("verse,", 13.19, 13.65),
    _w("able", 13.71, 13.89), _w("to", 13.91, 13.99), _w("show", 14.01, 14.15), _w("me", 14.17, 15.55),
    _w("Revelation", 16.35, 16.83),
]


def test_retext_keeps_word_count_and_spreads_timing():
    from tetclipper_pipeline.spec.glossary import retext

    out = retext(MISHEARD[3:7], "ebu tusome")
    assert [w["text"] for w in out] == ["ebu", "tusome", "show", "me"]
    assert [bool(w.get("hidden")) for w in out] == [False, False, True, True]
    assert out[0]["start"] == 13.71 and out[1]["end"] == 15.55
    assert out[0]["end"] == out[1]["start"]


def test_word_list_learns_from_an_edit_and_applies_to_new_clips(home):
    from tetclipper_pipeline.spec import glossary

    fixed = MISHEARD[:3] + glossary.retext(MISHEARD[3:7], "ebu tusome") + MISHEARD[7:]
    assert glossary.learn(MISHEARD, fixed) == 1
    data = glossary.load()
    assert data["fixes"] == [{"heard": "able to show me", "said": "ebu tusome", "count": 1}]
    assert "ebu tusome" in glossary.hotwords(data)

    new_clip, n = glossary.apply_fixes([_w("so", 1.0, 1.2), _w("Able", 1.3, 1.5), _w("to", 1.5, 1.6),
                                        _w("show", 1.6, 1.8), _w("me.", 1.8, 2.4), _w("Amen", 2.6, 3.0)])
    assert n == 1
    assert [w["text"] for w in new_clip if not w.get("hidden")] == ["so", "ebu", "tusome", "Amen"]


def test_word_list_ignores_one_word_swaps_deletions_and_rewrites(home):
    from tetclipper_pipeline.spec import glossary

    old = [_w("go", 0, 0.2), _w("to", 0.3, 0.4), _w("a", 0.5, 0.6), _w("place", 0.7, 1.0), _w("now", 1.2, 1.4)]
    swap = [dict(w) for w in old]
    swap[2]["text"] = "kwa"  # one word: context-specific
    assert glossary.learn(old, swap) == 0
    deleted = [dict(w) for w in old]
    deleted[1]["hidden"] = True  # deletion: context-specific
    assert glossary.learn(old, deleted) == 0
    long_old = [_w(f"w{i}", i, i + 0.5) for i in range(8)]
    rewrite = [dict(w, text=f"x{i}") for i, w in enumerate(long_old)]  # sentence rewrite, not a mishearing
    assert glossary.learn(long_old, rewrite) == 0
    assert glossary.load()["fixes"] == []
    # junk already on disk is dropped on the next save and never applied
    glossary.save({"phrases": [], "fixes": [{"heard": "a", "said": "kwa"}, {"heard": "able to show me", "said": "ebu tusome"}]})
    assert [f["heard"] for f in glossary.load()["fixes"]] == ["able to show me"]


def test_store_save_teaches_the_word_list_and_resolves_doubts(home, tmp_path):
    from tetclipper_pipeline.spec import glossary

    job = tmp_path / "job"
    spec = _spec(source={"src": "m.mp4", "start": 12, "end": 17, "width": 1920, "height": 1080},
                 words=MISHEARD, doubts=[{"from": 3, "to": 6, "reason": "too long", "alt": "ebu tusome"}])
    store.save(job, 0, spec, reason="built from analysis")
    edited = {**spec, "words": MISHEARD[:3] + glossary.retext(MISHEARD[3:7], "ebu tusome") + MISHEARD[7:]}
    saved = store.save(job, 0, edited, reason="use Swahili reading")
    assert saved["doubts"] == []  # the span was fixed
    assert glossary.load()["fixes"][0]["said"] == "ebu tusome"


def test_doubts_flag_the_swallowing_word_and_its_run():
    from tetclipper_pipeline.spec.doubts import detect

    spans = detect(MISHEARD)
    assert spans == [{"from": 3, "to": 6, "reason": "too long for the word (something may be missing)"}]
    unclear = detect(MISHEARD, scores={0: 0.1})  # unclear audio on a real word, apart from the run
    assert unclear[0] == {"from": 0, "to": 0, "reason": "unclear audio"} and unclear[1]["from"] == 3
    assert detect(MISHEARD, scores={7: 0.1})[-1] == {"from": 3, "to": 7, "reason": spans[0]["reason"]}  # adjacent: merged
    assert detect([_w("Amen", 1.0, 1.5), _w("I", 1.6, 1.7)], scores={1: 0.0}) == []  # short words: noise


def test_transcript_lists_doubts_for_claude(tmp_path):
    spec = _spec(source={"src": "m.mp4", "start": 12, "end": 17, "width": 1920, "height": 1080},
                 words=MISHEARD, doubts=[{"from": 3, "to": 6, "reason": "too long", "alt": "ebu tusome"}])
    text = transcript.render(tmp_path, spec)
    assert '?? [13.71] #3-6 "able to show me" (too long) · Swahili listen heard: "ebu tusome"' in text


# ---------- dead air ----------

def test_dead_air_natural_tight_reactions_and_fillers(tmp_path):
    from tetclipper_pipeline.spec import silence

    words = [_w("One", 0.0, 0.3), _w("two.", 0.4, 0.8), _w("Three", 1.6, 2.0),  # 0.8 s post-sentence pause
             _w("four", 4.0, 4.3),                                              # 2.0 s mid-sentence gap
             _w("um", 4.4, 4.7), _w("five", 4.8, 5.1), _w("six", 8.0, 8.3)]     # 2.9 s gap near a laugh
    (tmp_path / "events.json").write_text(json.dumps({"data": {"timeline": [{"type": "laugh", "start": 6.0, "end": 7.0}]}}))
    spec = _spec(source={"src": "m.mp4", "start": 0, "end": 8.3, "width": 1920, "height": 1080}, words=words)

    natural = silence.find(spec, tmp_path, "natural")
    assert natural["cuts"] == [{"start": 2.15, "end": 3.85}]  # breath kept both sides
    assert {k["reason"] for k in natural["kept"]} == {"natural sentence pause", "comedic timing (near a reaction)"}
    tight = silence.find(spec, tmp_path, "tight")
    assert {"start": 0.88, "end": 1.52} in tight["cuts"] and len(tight["cuts"]) == 2
    with_fillers = silence.find(spec, tmp_path, "natural", fillers=True)
    assert with_fillers["filler_words"] == [4]
    applied = silence.apply(spec, with_fillers)
    assert applied["words"][4]["hidden"] and validate(applied) == []
