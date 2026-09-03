import os

from backend.core.models import MockAdapter, ModelError, OpenAIAdapter


def test_mock_adapter_returns_scripted_text():
    m = MockAdapter(script=["hello"])
    result = m.generate("prompt")
    assert result.text == "hello"


def test_mock_adapter_raises_on_empty_script_response():
    m = MockAdapter(script=[])
    try:
        m.generate("prompt")
        assert False, "expected ModelError on empty response"
    except ModelError:
        pass


def test_openai_adapter_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adapter = OpenAIAdapter()
    assert adapter.available() is False
    try:
        adapter.generate("prompt")
        assert False, "expected ModelError when key is missing"
    except ModelError:
        pass


def test_openai_adapter_available_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    adapter = OpenAIAdapter()
    assert adapter.available() is True
