"""End-to-end agent-loop scenarios against ScriptedProvider.

These cover the paths a live model actually hits: text, tools, deny,
multi-tool, streaming deltas, spawn, and 429 retry. No network.
"""

from __future__ import annotations

import asyncio

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import (
    EventBus,
    StreamTextDelta,
    UsageUpdated,
)
from open_claude_code.providers.base import ToolUseBlock

from tests.fakes import ScriptedProvider, ScriptedTurn


def _config(**kwargs) -> AgentConfig:
    return AgentConfig(provider_retry_base_delay=0.0, **kwargs)


def _echo_tools():
    calls: list[str] = []

    async def echo(message: str) -> str:
        calls.append(message)
        return f"echoed:{message}"

    tools = {
        "echo": {
            "function": echo,
            "schema": {
                "name": "echo",
                "description": "Echo",
                "input_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
        }
    }
    return tools, calls


def test_scripted_text_emits_usage_and_stream_deltas():
    provider = ScriptedProvider([ScriptedTurn.reply("Hello world")])
    deltas: list[str] = []
    usage: list[UsageUpdated] = []
    bus = EventBus()

    async def on_delta(event: StreamTextDelta) -> None:
        deltas.append(event.text)

    async def on_usage(event: UsageUpdated) -> None:
        usage.append(event)

    bus.on(StreamTextDelta, on_delta)
    bus.on(UsageUpdated, on_usage)
    agent = Agent(provider=provider, event_bus=bus, tools={}, config=_config())
    assert asyncio.run(agent.run("hi")) == "Hello world"
    assert "".join(deltas) == "Hello world"
    assert usage and usage[0].input_tokens == 3
    assert provider.remaining == 0


def test_xml_tool_call_from_openai_compat_is_executed():
    """Local models that narrate <tool_call> JSON still run the tool."""
    from open_claude_code.providers.openai import OpenAIProvider

    from tests.test_providers import _FakeStream, _bind_create, _completion, _delta_chunk

    tools, calls = _echo_tools()
    xml = '<tool_call>{"name": "echo", "arguments": {"message": "ping"}}</tool_call>'
    turn = {"n": 0}

    async def create(**kwargs):
        turn["n"] += 1
        if turn["n"] == 1:
            if kwargs.get("stream"):
                return _FakeStream([_delta_chunk(xml, finish="stop")])
            return _completion(xml)
        if kwargs.get("stream"):
            return _FakeStream([_delta_chunk("done", finish="stop")])
        return _completion("done")

    provider = _bind_create(OpenAIProvider(model="qwen2.5", api_key="test"), create)
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=_config())
    assert asyncio.run(agent.run("echo ping")) == "done"
    assert calls == ["ping"]


def test_ollama_native_tool_call_round_trips_history():
    """Agent loop against native /api/chat: tool call, then tool result is resent."""
    import json

    from open_claude_code.providers.ollama import OllamaProvider

    from tests.test_providers import _FakeOllamaResponse, _bind_ollama

    tools, calls = _echo_tools()
    tool_turn = json.dumps({
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {"name": "echo", "arguments": {"message": "ping"}},
            }],
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 6,
        "eval_count": 2,
    })
    final_turn = json.dumps({
        "message": {"role": "assistant", "content": "echoed it"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 9,
        "eval_count": 3,
    })
    provider, client = _bind_ollama(OllamaProvider(model="ollama/llama3.2"), [
        _FakeOllamaResponse(lines=[tool_turn]),
        _FakeOllamaResponse(lines=[final_turn]),
    ])
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=_config())
    assert asyncio.run(agent.run("echo ping")) == "echoed it"
    assert calls == ["ping"]
    assert all(req["url"].endswith("/api/chat") for req in client.requests)
    assert client.requests[0]["json"]["options"]["num_ctx"] == 32768
    second = client.requests[1]["json"]["messages"]
    assert any(msg.get("role") == "tool" and "echoed:ping" in str(msg.get("content")) for msg in second)


def test_scripted_tool_then_final_text():
    tools, calls = _echo_tools()
    provider = ScriptedProvider([
        ScriptedTurn.tools(ToolUseBlock(id="t1", name="echo", input={"message": "ping"})),
        ScriptedTurn.reply("done"),
    ])
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=_config())
    assert asyncio.run(agent.run("echo ping")) == "done"
    assert calls == ["ping"]


def test_scripted_tool_denied_by_listener():
    tools, calls = _echo_tools()

    async def deny(event) -> bool:
        return False

    provider = ScriptedProvider([
        ScriptedTurn.tools(ToolUseBlock(id="t1", name="echo", input={"message": "nope"})),
        ScriptedTurn.reply("acknowledged"),
    ])
    bus = EventBus()
    bus.on_approval(deny)
    agent = Agent(provider=provider, event_bus=bus, tools=tools, config=_config())
    assert asyncio.run(agent.run("echo")) == "acknowledged"
    assert calls == []


def test_scripted_multi_tool_in_one_turn():
    tools, calls = _echo_tools()
    provider = ScriptedProvider([
        ScriptedTurn.tools(
            ToolUseBlock(id="t1", name="echo", input={"message": "one"}),
            ToolUseBlock(id="t2", name="echo", input={"message": "two"}),
        ),
        ScriptedTurn.reply("both done"),
    ])
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=_config())
    assert asyncio.run(agent.run("echo twice")) == "both done"
    assert calls == ["one", "two"]


def test_scripted_429_retries_then_succeeds():
    provider = ScriptedProvider([
        ScriptedTurn.rate_limit(),
        ScriptedTurn.reply("recovered"),
    ])
    usage: list[UsageUpdated] = []
    bus = EventBus()

    async def on_usage(event: UsageUpdated) -> None:
        usage.append(event)

    bus.on(UsageUpdated, on_usage)
    agent = Agent(provider=provider, event_bus=bus, tools={}, config=_config())
    assert asyncio.run(agent.run("go")) == "recovered"
    assert len(provider.calls) == 2
    assert usage and usage[0].output_tokens == 2


def test_scripted_spawn_child_stays_on_parent_provider():
    writes: list[tuple[str, str]] = []

    async def write_file(file_path: str, content: str) -> str:
        writes.append((file_path, content))
        return "written"

    provider = ScriptedProvider([
        ScriptedTurn.tools(ToolUseBlock(
            id="spawn-1",
            name="spawn_agent",
            input={"task": "investigate", "agent_type": "explore"},
        )),
        ScriptedTurn.tools(ToolUseBlock(
            id="write-1",
            name="write_file",
            input={"file_path": "unsafe.txt", "content": "no"},
        )),
        ScriptedTurn.reply("Investigation complete"),
        ScriptedTurn.reply("Parent complete"),
    ])
    tools = {
        "spawn_agent": {
            "function": None,
            "schema": {"name": "spawn_agent", "input_schema": {"type": "object"}},
        },
        "write_file": {
            "function": write_file,
            "schema": {"name": "write_file", "input_schema": {"type": "object"}},
        },
    }
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=_config())
    assert asyncio.run(agent.run("delegate this")) == "Parent complete"
    assert writes == []
    assert provider.remaining == 0
