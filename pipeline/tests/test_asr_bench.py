"""The ears test: reference from edit history, scoring, the Swahili tagger,
and the second listen's text clean-up it shares."""
import json

from tetclipper_pipeline.asr import bench, swahili
from tetclipper_pipeline.spec import doubts, store


def _words(texts):
    """0.3 s words, 0.1 s apart; a word ending in "." is followed by a 2 s pause."""
    out, t = [], 10.0
    for text in texts:
        out.append({"text": text, "start": round(t, 3), "end": round(t + 0.3, 3)})
        t += 2.3 if text.endswith(".") else 0.4
    return out


def _save(hist, n, words, reason, spans=()):
    (hist / f"{n:04d}.json").write_text(json.dumps({"words": words, "doubts": [{"from": a, "to": b} for a, b in spans]}), encoding="utf-8")
    (hist / f"{n:04d}.reason").write_text(reason, encoding="utf-8")


def test_reference_comes_from_what_the_user_checked(tmp_path):
    hist = store.clip_dir(tmp_path, 0) / "history"
    hist.mkdir(parents=True)
    base = _words(["Then", "you", "can", "go.", "And", "it", "is", "for", "me", "to", "go", "to", "work", "on", "a", "hill."])
    _save(hist, 1, base, "built from analysis")
    _save(hist, 2, base, "checked captions: 2 span(s) to verify", [(1, 2), (5, 6)])
    _save(hist, 3, base, "caption is right", [(5, 6)])
    w = [dict(x) for x in base]
    w[9]["text"] = "kukosana na watu"
    _save(hist, 4, w, 'fix word "to" → "kukosana na watu"', [(5, 6)])
    w = [dict(x) for x in w]
    w[10]["hidden"] = True
    _save(hist, 5, w, 'fix word "go" → ""', [(5, 6)])
    w = [dict(x) for x in w]
    w[12]["text"] = "watu"
    _save(hist, 6, w, 'fix word "work" → "watu"', [(5, 6)])
    # Claude's later guess changes the word count: nothing after it counts.
    _save(hist, 7, w[:-1], "claude", [])
    segs = bench.from_history(tmp_path, 0)
    # Each piece grows to whole words around it, up to a long pause: every
    # word in the audio is in the reference.
    assert [(s["kind"], s["ref"], s["heard"]) for s in segs] == [
        ("checked", "Then you can go.", "Then you can go."),
        ("retyped", "And it is for me kukosana na watu to watu on a", "And it is for me to go to work on a"),
    ]
    assert segs[0]["start"] == round(base[0]["start"] - doubts.PAD_SEC, 3)  # nothing before: padded
    assert segs[0]["end"] == round(base[3]["end"] + doubts.PAD_SEC, 3)  # a 2 s pause after: padded
    assert all(s["audio"].endswith("audio16k.wav") for s in segs)


def test_pieces_are_cut_between_words():
    words = [{"text": t, "start": 1.0 * i, "end": 1.0 * i + 0.8} for i, t in enumerate("a b c d e f g h".split())]
    a, b, lo, hi = bench._widen(words, 3, 3)
    assert words[b]["end"] - words[a]["start"] >= bench.MIN_SEC
    assert lo == (words[a - 1]["end"] + words[a]["start"]) / 2 and hi == (words[b]["end"] + words[b + 1]["start"]) / 2


def test_scoring_counts_word_letter_and_swahili_errors():
    s = bench.score("for me kukosana na watu", "for me to go to work on a")
    assert s["words"] == 5 and s["errors"] == 6  # 3 swapped + 3 extra
    assert s["sw_words"] == 3 and s["sw_errors"] == 3
    exact = bench.score("Yaani, you can!", "yaani you can")
    assert exact["errors"] == 0 and exact["char_errors"] == 0
    assert bench.align(["a", "b"], ["a", "x", "b"]) == [("a", "a"), (None, "x"), ("b", "b")]


def test_summary_ranks_by_swahili_errors():
    segs = [{"id": "1", "start": 0, "end": 30, "ref": "kuna place tu"}]
    rows = [
        {"model": "turbo", "mode": "en", "id": "1", "text": "corner place to", "secs": 3.0, "error": None},
        {"model": "paza", "mode": "sw", "id": "1", "text": "kuna place tu", "secs": 4.5, "error": None},
    ]
    summary = bench.summarize(segs, rows)
    assert [t["model"] for t in summary] == ["paza", "turbo"]
    assert summary[0]["sw_wer"] == 0 and summary[1]["sw_wer"] == 1.0
    assert summary[0]["secs_per_min"] == 9.0


def test_swahili_tagger():
    for w in ["anasema", "tutaenda", "nimeona", "kukosana", "Yesu,", "watu", "kwa", "usiignore", "Bwana"]:
        assert swahili.is_swahili(w), w
    for w in ["the", "something", "unable", "alike", "aside", "place", "pole", "tuna", "using", "passive"]:
        assert not swahili.is_swahili(w), w
    assert swahili.share("kuna place tu") == 2 / 3


def test_second_listen_text_cleanup():
    assert doubts.tidy("ebu tusome, hapa, hapa, hapa") == "ebu tusome, hapa"
    assert doubts.tidy("Mungu ni mwema mwema,") == "Mungu ni mwema"
    assert doubts.is_alternative("able to show me", "ebu tusome")
    assert not doubts.is_alternative("you can", "you can speak to")  # the same words plus padding
    assert not doubts.is_alternative("Yes.", "yes")
    assert not doubts.is_alternative("you can", "")
