"""Tests for the core agent loop."""

import asyncio

from open_claude_code.agent import Agent
from open_claude_code.events import EventBus, PostToolUse, Stop, SubagentStart, SubagentStop, Thinking
from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock, ThinkingBlock, ToolUseBlock


class MockProvider(Provider):
    """Returns scripted responses in order."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def send(self, messages, tools, system_prompt) -> ProviderResponse:
        return self._responses.pop(0)


def test_text_response():
    """Agent returns text and emits Stop event."""
    events = []

    async def collect(event):
        events.append(event)

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="Hello!")])
    ])

    bus = EventBus()
    bus.on(Stop, collect)

    agent = Agent(provider=provider, event_bus=bus, tools={})
    result = asyncio.run(agent.run("hi"))

    assert result == "Hello!"
    assert len(events) == 1
    assert events[0].text == "Hello!"


def test_tool_call_approved():
    """Agent executes tool when approved."""
    calls = []

    async def mock_tool(message: str) -> str:
        calls.append(message)
        return f"echoed: {message}"

    tools = {
        "echo": {
            "function": mock_tool,
            "schema": {"name": "echo", "description": "Echo", "input_schema": {
                "type": "object", "properties": {"message": {"type": "string"}},
                "required": ["message"],
            }},
        }
    }

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="echo", input={"message": "test"})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Done!")]),
    ])

    bus = EventBus()
    agent = Agent(provider=provider, event_bus=bus, tools=tools)
    result = asyncio.run(agent.run("echo test"))

    assert result == "Done!"
    assert calls == ["test"]


def test_tool_call_denied():
    """Agent uses denial message when listener returns False."""
    async def deny(event):
        return False

    tools = {
        "dangerous": {
            "function": lambda: None,
            "schema": {"name": "dangerous", "description": "Bad", "input_schema": {
                "type": "object", "properties": {}, "required": [],
            }},
        }
    }

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="dangerous", input={})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="OK denied.")]),
    ])

    bus = EventBus()
    bus.on_approval(deny)

    agent = Agent(provider=provider, event_bus=bus, tools=tools)
    result = asyncio.run(agent.run("do something"))

    assert result == "OK denied."


def test_thinking_emitted():
    """Agent emits Thinking event."""
    events = []

    async def collect(event):
        events.append(event)

    provider = MockProvider([
        ProviderResponse(
            thinking=ThinkingBlock(thinking="hmm...", signature="sig1"),
            content=[TextBlock(text="42")]
        )
    ])

    bus = EventBus()
    bus.on(Thinking, collect)

    agent = Agent(provider=provider, event_bus=bus, tools={})
    result = asyncio.run(agent.run("what?"))

    assert result == "42"
    assert len(events) == 1
    assert events[0].text == "hmm..."


def test_conversation_history():
    """History accumulates across multiple run() calls."""
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="First")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Second")]),
    ])

    bus = EventBus()
    agent = Agent(provider=provider, event_bus=bus, tools={})

    asyncio.run(agent.run("one"))
    asyncio.run(agent.run("two"))

    assert len(agent.history) == 4
    assert agent.history[0]["role"] == "user"
    assert agent.history[1]["role"] == "assistant"
    assert agent.history[2]["role"] == "user"
    assert agent.history[3]["role"] == "assistant"


def test_post_tool_use_events():
    """PostToolUse events are emitted correctly."""
    post_events = []

    async def collect(event):
        post_events.append(event)

    async def mock_tool(msg: str) -> str:
        return f"result:{msg}"

    tools = {
        "echo": {
            "function": mock_tool,
            "schema": {"name": "echo", "description": "Echo", "input_schema": {
                "type": "object", "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            }},
        }
    }

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="echo", input={"msg": "test"})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="done")]),
    ])

    bus = EventBus()
    bus.on(PostToolUse, collect)

    agent = Agent(provider=provider, event_bus=bus, tools=tools)
    asyncio.run(agent.run("echo test"))

    assert len(post_events) == 1
    assert post_events[0].tool_name == "echo"
    assert post_events[0].result == "result:test"


def test_unknown_tool():
    """Agent handles unknown tools gracefully."""
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="nonexistent", input={})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="OK")]),
    ])

    bus = EventBus()
    agent = Agent(provider=provider, event_bus=bus, tools={})
    result = asyncio.run(agent.run("test"))
    assert result == "OK"
