"""Brain selection: Claude Code is the default; your own Gemini key resolves
to Google's endpoint (or an override base URL). No network is touched."""
import pytest

from tetclipper_pipeline import config
from tetclipper_pipeline.scoring import llm as llm_mod


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TETCLIPPER_HOME", str(tmp_path / "home"))
    for var in ("TETCLIPPER_GEMINI_API_KEY", "TETCLIPPER_GEMINI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    config.ensure_home()


def test_default_brain_is_claude_code():
    assert config.Settings().llm_mode == "claude"
    assert config.Settings.from_json({}).llm_mode == "claude"
    # a job snapshotted on gemini keeps gemini
    assert config.Settings.from_json({"llm_mode": "gemini"}).llm_mode == "gemini"


def test_claude_mode_needs_no_key():
    client = llm_mod.make_client("claude")
    assert client.backend == "claude"


def test_gemini_endpoint(monkeypatch):
    monkeypatch.setenv("TETCLIPPER_GEMINI_API_KEY", "AIzaTEST")
    ep = llm_mod.resolve_endpoint("gemini")
    assert ep.provider == "gemini"
    assert ep.key == "AIzaTEST"
    assert ep.model == "gemini-flash-latest"
    assert ep.url() == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    )
    monkeypatch.setenv("TETCLIPPER_GEMINI_BASE_URL", "http://proxy.test")
    assert llm_mod.resolve_endpoint("gemini").url().startswith("http://proxy.test/v1beta/models/gemini-flash-latest")


def test_gemini_without_key_is_actionable():
    with pytest.raises(llm_mod.LlmError) as exc:
        llm_mod.resolve_endpoint("gemini")
    assert "Claude Code" in str(exc.value)
