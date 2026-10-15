"""Claude Code handoff (llm_mode "claude"): pending prompts are batched into
one request, answers land in the LLM cache, and the next pass hits it."""
import json

import pytest

from tetclipper_pipeline.scoring import brain, rubric

SCHEMA = rubric.T1_SCHEMA
GOOD = {
    "hook": 6, "hook_type": "question", "funniness": 2, "punchline_index": -1,
    "shock": 3, "curiosity_gap": 5, "value": 7, "self_contained": True,
    "bait_phrases": [], "summary": "A pastor contrasts power and love.",
}


@pytest.fixture
def job_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path))
    d = tmp_path / "jobs" / "job-1"
    d.mkdir(parents=True)
    return d


def _ask(client, prompt):
    try:
        return client.generate_json(prompt, SCHEMA)
    except brain.BrainPending:
        return None


def test_misses_are_batched_into_one_request(job_dir):
    client = brain.ClaudeHandoffClient()
    assert _ask(client, "rate A") is None
    assert _ask(client, "rate B") is None
    assert _ask(client, "rate A") is None  # duplicates are not re-queued
    with pytest.raises(brain.AwaitingBrain) as exc:
        client.checkpoint(job_dir, "moment-scoring")
    assert exc.value.count == 2
    request = brain.load_request(job_dir)
    assert [i["prompt"] for i in request["items"]] == ["rate A", "rate B"]


def test_answers_become_cache_hits_and_clear_the_request(job_dir):
    client = brain.ClaudeHandoffClient()
    _ask(client, "rate A")
    with pytest.raises(brain.AwaitingBrain):
        client.checkpoint(job_dir, "moment-scoring")
    item_id = brain.load_request(job_dir)["items"][0]["id"]

    report = brain.apply_answers(job_dir, {item_id: GOOD})
    assert report == {"written": 1, "missing": [], "errors": {}}

    resumed = brain.ClaudeHandoffClient()
    assert resumed.generate_json("rate A", SCHEMA) == GOOD
    resumed.checkpoint(job_dir, "moment-scoring")  # nothing pending: no raise
    assert brain.load_request(job_dir) is None


def test_invalid_answers_are_rejected(job_dir):
    client = brain.ClaudeHandoffClient()
    _ask(client, "rate A")
    with pytest.raises(brain.AwaitingBrain):
        client.checkpoint(job_dir, "moment-scoring")
    item_id = brain.load_request(job_dir)["items"][0]["id"]
    bad = {**GOOD, "hook": "high", "hook_type": "meme"}
    del bad["summary"]
    report = brain.apply_answers(job_dir, {item_id: bad})
    assert report["written"] == 0
    assert set(report["errors"][item_id]) == {
        "missing summary", "hook should be integer",
        "hook_type must be one of ['question', 'bold_claim', 'story_open', 'absurd', 'conflict', 'none']",
    }


def test_render_prints_shared_instructions_once(job_dir):
    client = brain.ClaudeHandoffClient()
    for body in ("first transcript", "second transcript"):
        _ask(client, f"You are rating a clip.\n{body}\nScore honestly.")
    with pytest.raises(brain.AwaitingBrain):
        client.checkpoint(job_dir, "moment-scoring")
    text = brain.render_request(brain.load_request(job_dir))
    assert text.count("You are rating a clip.") == 1
    assert text.count("Score honestly.") == 1
    assert "first transcript" in text and "second transcript" in text
    assert json.dumps(SCHEMA, sort_keys=True) in text
