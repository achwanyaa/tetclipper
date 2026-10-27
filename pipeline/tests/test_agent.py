"""Studio chat on an API model (server/agent.py): settings, tools and both
tool loops, with stand-in clients (no network, no API key)."""
import json
from types import SimpleNamespace as NS

import pytest

import tetclipper_pipeline.server.app  # noqa: F401  (the server's import order)
from tetclipper_pipeline.server import agent
from tetclipper_pipeline.spec import store


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


@pytest.fixture
def tools(tmp_path):
    job = tmp_path / "job"
    spec = {
        "version": 1,
        "source": {"src": "media.mp4", "start": 5.0, "end": 20.0, "width": 1920, "height": 1080},
        "intro": None,
        "cuts": [],
        "words": [
            {"text": "Hello", "start": 5.2, "end": 5.6},
            {"text": "world.", "start": 5.7, "end": 6.1},
            {"text": "Next", "start": 7.5, "end": 7.9},
        ],
        "captions": {"enabled": True, "style": "hormozi"},
        "crop": {"keyframes": []},
        "effects": [],
        "progressBar": {"enabled": False, "color": "#FFD700"},
    }
    store.save(job, 0, spec, reason="test")
    return agent.ClipTools(job, 0, "claude: test", lambda s, reason: store.save(job, 0, s, reason=reason))


def test_settings_default_mask_and_require_a_key(home):
    assert agent.load_settings()["provider"] == "claude-code"
    with pytest.raises(ValueError, match="API key"):
        agent.save_settings("deepseek", "deepseek-chat")
    agent.save_settings("deepseek", "deepseek-chat", key="sk-abcdefghijklmnop1234")
    pub = agent.public_settings()
    deepseek = next(p for p in pub["providers"] if p["id"] == "deepseek")
    assert pub["provider"] == "deepseek" and deepseek["key"] == "sk-abc…1234"
    assert "sk-abcdefghijklmnop1234" not in json.dumps(pub)
    assert agent.engine_label() == {"provider": "deepseek", "model": "deepseek-chat", "label": "deepseek-chat", "ready": True}


def test_tools_merge_validate_and_reject(tools):
    out, failed = tools.run("update_spec", {"changes": {"captions": {"style": "sermon"}}})
    assert not failed and out.startswith("Saved")
    spec = store.load(tools.job_dir, 0)
    assert spec["captions"] == {"enabled": True, "style": "sermon"}

    out, _ = tools.run("update_spec", {"changes": {"captions": {"position": 7}}})
    assert out.startswith("Not saved") and "position" in out
    assert "position" not in store.load(tools.job_dir, 0)["captions"]

    tools.run("edit_words", {"edits": [{"index": 1, "text": "there.", "emphasis": True}]})
    assert store.load(tools.job_dir, 0)["words"][1] == {"text": "there.", "start": 5.7, "end": 6.1, "emphasis": True}
    assert "#2 7.50-7.90 Next" in tools.run("find_words", {"text": "next"})[0]

    tools.run("add_items", {"field": "effects", "items": [{"type": "punch-in", "at": 6, "duration": 2, "amount": 1.2}]})
    assert len(store.load(tools.job_dir, 0)["effects"]) == 1
    tools.run("remove_items", {"field": "effects", "indexes": [0]})
    assert store.load(tools.job_dir, 0)["effects"] == []
    assert tools.run("nope", {}) == ("Unknown tool nope.", True)


class FakeAnthropic:
    """First reply calls update_spec; the second answers."""

    def __init__(self):
        self.calls, self.messages, self.beta = 0, self, NS(messages=self)

    def create(self, **kw):
        self.calls += 1
        usage = NS(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0)
        if self.calls == 1:
            call = NS(type="tool_use", id="t1", name="update_spec", input={"changes": {"captions": {"style": "beast"}}})
            return NS(stop_reason="tool_use", usage=usage, content=[call])
        result = kw["messages"][-1]["content"][0]
        assert result["type"] == "tool_result" and result["tool_use_id"] == "t1"
        return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Beast captions now.")])


class FakeOpenAI:
    def __init__(self):
        self.calls, self.chat = 0, NS(completions=self)

    def create(self, **kw):
        self.calls += 1
        usage = NS(prompt_tokens=900, completion_tokens=80)
        if self.calls == 1:
            call = NS(id="c1", function=NS(name="update_spec", arguments=json.dumps({"changes": {"captions": {"style": "minimal"}}})))
            return NS(usage=usage, choices=[NS(finish_reason="tool_calls", message=NS(content=None, tool_calls=[call]))])
        assert kw["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": kw["messages"][-1]["content"]}
        return NS(usage=usage, choices=[NS(finish_reason="stop", message=NS(content="Minimal now.", tool_calls=None))])


def test_find_moments_judging_with_an_api_model(tmp_path, monkeypatch):
    """Online Find moments: the admin's model answers the judging prompts;
    what's missing is asked again and the rounds' answers are combined."""
    from tetclipper_pipeline.scoring import auto_brain, brain

    schema = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}
    request = {"job_id": "j", "purpose": "score", "items": [
        {"id": "a", "prompt": "Rate moment A", "schema": schema},
        {"id": "b", "prompt": "Rate moment B", "schema": schema},
    ]}
    replies = iter(['```json\n{"a": {"score": 7}}\n```', '{"b": {"score": 4}}'])
    asked = []

    def complete(system, prompt):
        asked.append(prompt)
        return next(replies)

    applied = []

    def apply(job_dir, answers):
        applied.append(dict(answers))
        return {"written": len(answers), "missing": [i["id"] for i in request["items"] if i["id"] not in answers], "errors": {}}

    monkeypatch.setattr(brain, "apply_answers", apply)
    auto_brain._answer_with_api(tmp_path, request, lambda f, m: None, NS(complete=complete))
    assert applied[-1] == {"a": {"score": 7}, "b": {"score": 4}}
    assert "--- id b" in asked[1] and "--- id a" not in asked[1]
    assert "tetclipper brain answer" not in asked[0]


@pytest.mark.parametrize("loop, client, style", [
    (agent._loop_anthropic, FakeAnthropic, "beast"),
    (agent._loop_openai, FakeOpenAI, "minimal"),
])
def test_tool_loops_edit_then_answer(tools, loop, client, style):
    events, replies = [], []
    usage = {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0}
    error = loop(client(), "model", "system", [], "change the captions", tools,
                 lambda kind, **f: events.append(kind), replies, usage)
    assert error is None and len(replies) == 1
    assert events == ["tool", "text"] and usage["in"] > 0
    assert store.load(tools.job_dir, 0)["captions"]["style"] == style
