"""Unit tests for AgentClient and MockAgent."""
import pytest
from modules.schemas import RuntimeConfig
from modules.agent_client import AgentClient


def test_mock_mode_when_no_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    runtime = RuntimeConfig(llm_enabled="auto")
    client = AgentClient(runtime)
    assert client.is_mock()


def test_mock_mode_when_disabled(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    runtime = RuntimeConfig(llm_enabled="false")
    client = AgentClient(runtime)
    assert client.is_mock()


def test_mock_agent_returns_valid_json(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    runtime = RuntimeConfig(llm_enabled="auto")
    client = AgentClient(runtime)
    response = client.call("system", "user", {"scenario": "l4_review"})
    assert not response.error
    assert "decision" in response.parsed
