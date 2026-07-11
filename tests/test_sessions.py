"""Tests for the durable session ledger."""

import json
import asyncio

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus
from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock
from open_claude_code.sessions import SessionStore


class _TextProvider(Provider):
    @property
    def model_name(self) -> str:
        return "session-test-model"

    async def send(self, messages, tools, system_prompt) -> ProviderResponse:
        return ProviderResponse(thinking=None, content=[TextBlock(text="completed")])


def test_session_persists_history_and_redacts_config(tmp_path):
    config = AgentConfig(
        api_key="top-secret",
        sessions_dir=str(tmp_path / "sessions"),
        mcp_servers=[{"name": "private", "env": {"ACCESS_TOKEN": "secret-token"}}],
    )
    store = SessionStore.create(config=config, model="mock-model", mode="agent", cwd=tmp_path)

    first = {"role": "user", "content": "Please inspect the project"}
    second = {"role": "assistant", "content": "I will inspect it."}
    store.record_history(first)
    store.record_history(second)
    store.record_tool_call("read_file", "tool-1", {"file_path": "README.md"}, approved=True)
    store.record_tool_result("read_file", "tool-1", "contents")
    store.close()

    assert store.load_history() == [first, second]
    metadata = json.loads(store.metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "closed"
    assert metadata["config"]["api_key"] == "[redacted]"
    assert metadata["config"]["mcp_servers"][0]["env"]["ACCESS_TOKEN"] == "[redacted]"


def test_session_can_resume_and_list(tmp_path):
    config = AgentConfig(sessions_dir=str(tmp_path / "sessions"))
    original = SessionStore.create(config=config, model="mock-model", mode="plan", cwd=tmp_path)
    original.record_history({"role": "user", "content": "original task"})
    original.close()

    resumed = SessionStore.resume(original.session_id, config=config, cwd=tmp_path)
    resumed.record_history({"role": "assistant", "content": "resumed response"})

    assert resumed.load_history() == [
        {"role": "user", "content": "original task"},
        {"role": "assistant", "content": "resumed response"},
    ]
    sessions = SessionStore.list_sessions(config=config, cwd=tmp_path)
    assert [item["session_id"] for item in sessions] == [original.session_id]
    assert sessions[0]["resume_count"] == 1


def test_agent_writes_resume_ready_history(tmp_path):
    config = AgentConfig(sessions_dir=str(tmp_path / "sessions"))
    store = SessionStore.create(config=config, model="session-test-model", mode="agent", cwd=tmp_path)
    agent = Agent(
        provider=_TextProvider(),
        event_bus=EventBus(),
        tools={},
        config=config,
        session_store=store,
    )

    assert asyncio.run(agent.run("finish this task")) == "completed"
    store.close()

    resumed = SessionStore.resume(store.session_id, config=config, cwd=tmp_path)
    assert resumed.load_history() == [
        {"role": "user", "content": "finish this task"},
        {"role": "assistant", "content": "completed"},
    ]
