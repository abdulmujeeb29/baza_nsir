import pytest

from app import llm
from app.llm import FakeLLM, LLMError, LLMResponse, ToolCall


def test_fake_llm_replays_script():
    fake = FakeLLM([LLMResponse("", [ToolCall("1", "search_catalog", {"query": "poverty"})]), LLMResponse("done")])
    first = fake.chat_with_tools([{"role": "user", "content": "q"}], [{"name": "search_catalog"}])
    assert first.tool_calls[0].name == "search_catalog"
    assert fake.chat_with_tools([], []).text == "done"
    assert fake.calls[0]["tools"] == ["search_catalog"]
    assert "could not" in fake.chat_with_tools([], []).text


def test_fake_llm_raises_scripted_errors():
    fake = FakeLLM([LLMError("busy")])
    with pytest.raises(LLMError):
        fake.chat_with_tools([], [])


def test_missing_key_is_a_friendly_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(LLMError, match="API key"):
        llm.get_llm()


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-value")
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(LLMError, match="Unknown"):
        llm.get_llm()


def test_providers_build(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-value")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/openai/v1")
    for provider in ["azure", "openai", "gemini", "anthropic"]:
        monkeypatch.setenv("LLM_PROVIDER", provider)
        assert hasattr(llm.get_llm(), "chat_with_tools")
