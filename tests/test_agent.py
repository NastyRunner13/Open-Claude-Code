"""Tests for the core agent loop."""

import asyncio

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus, PostToolUse, Stop, SubagentStart, SubagentStop, Thinking, ToolDenied
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


def test_context_compaction_can_be_disabled():
    """Agent respects AgentConfig.context_compaction=False."""
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="OK")])
    ])

    bus = EventBus()
    agent = Agent(
        provider=provider,
        event_bus=bus,
        tools={},
        config=AgentConfig(context_compaction=False),
    )
    called = False

    async def fail_if_called(history):
        nonlocal called
        called = True
        return history

    agent._context_mgr.auto_compact_async = fail_if_called  # type: ignore[method-assign]

    result = asyncio.run(agent.run("do not compact"))
    assert result == "OK"
    assert called is False


def test_disallowed_tool_is_blocked_before_approval():
    """A policy denial cannot be bypassed by the default approval behavior."""
    calls = []
    denials = []

    async def dangerous_tool() -> str:
        calls.append(True)
        return "should not run"

    async def collect(event):
        denials.append(event)

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="dangerous", input={})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Policy respected")]),
    ])
    bus = EventBus()
    bus.on(ToolDenied, collect)
    agent = Agent(
        provider=provider,
        event_bus=bus,
        tools={
            "dangerous": {
                "function": dangerous_tool,
                "schema": {"name": "dangerous", "input_schema": {"type": "object"}},
            }
        },
        config=AgentConfig(disallowed_tools=["dangerous"]),
    )

    assert asyncio.run(agent.run("do the thing")) == "Policy respected"
    assert calls == []
    assert len(denials) == 1
    assert denials[0].tool_name == "dangerous"


def test_subagent_is_read_only_by_default():
    """Child agents cannot write even if the parent has workspace-write access."""
    writes = []

    async def write_file(file_path: str, content: str) -> str:
        writes.append((file_path, content))
        return "written"

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="spawn-1",
                name="spawn_agent",
                input={"task": "investigate", "agent_type": "explore"},
            )
        ]),
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="write-1",
                name="write_file",
                input={"file_path": "unsafe.txt", "content": "no"},
            )
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Investigation complete")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Parent complete")]),
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

    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, config=AgentConfig())
    assert asyncio.run(agent.run("delegate this")) == "Parent complete"
    assert writes == []


def test_subagent_cannot_elevate_above_parent():
    """A child requesting full-access stays at the parent's workspace-write cap."""
    shell_calls = []

    async def run_shell(command: str, timeout: int = 60, cwd: str = "") -> str:
        shell_calls.append(command)
        return "ran"

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="spawn-1",
                name="spawn_agent",
                input={"task": "elevate me", "permission_mode": "full-access"},
            )
        ]),
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="shell-1",
                name="run_shell",
                input={"command": "python -c \"open('x','w')\""},
            )
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Child complete")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Parent complete")]),
    ])
    tools = {
        "spawn_agent": {
            "function": None,
            "schema": {"name": "spawn_agent", "input_schema": {"type": "object"}},
        },
        "run_shell": {
            "function": run_shell,
            "schema": {"name": "run_shell", "input_schema": {"type": "object"}},
        },
    }

    agent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=tools,
        config=AgentConfig(permission_mode="workspace-write"),
    )
    assert asyncio.run(agent.run("delegate this")) == "Parent complete"
    assert shell_calls == []


def test_clamp_permission_mode_never_elevates():
    from open_claude_code.tools.policy import clamp_permission_mode

    assert clamp_permission_mode("full-access", "read-only") == "read-only"
    assert clamp_permission_mode("full-access", "workspace-write") == "workspace-write"
    assert clamp_permission_mode("workspace-write", "read-only") == "read-only"
    assert clamp_permission_mode("read-only", "full-access") == "read-only"
    assert clamp_permission_mode("", "workspace-write") == "read-only"
    assert clamp_permission_mode("", "workspace-write", "inherit") == "workspace-write"
    assert clamp_permission_mode("full-access", "workspace-write", "inherit") == "workspace-write"
    assert clamp_permission_mode("all", "read-only") == "read-only"
    assert clamp_permission_mode("read-write", "full-access") == "workspace-write"
