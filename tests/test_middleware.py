"""Tests for the middleware architecture."""

import asyncio

import pytest

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus
from open_claude_code.middleware import Middleware, MiddlewareManager
from open_claude_code.middleware.plugins import PluginMiddleware
from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock, ToolUseBlock


class DummyMiddleware(Middleware):
    """Simple middleware for testing."""

    def __init__(self, mw_name: str = "dummy", tools: dict | None = None,
                 prompt: str = "", slash_cmd: str | None = None) -> None:
        self._name = mw_name
        self._tools = tools or {}
        self._prompt = prompt
        self._slash_cmd = slash_cmd
        self.started = False
        self.shutdown_called = False
        self.turns_started: list[str] = []
        self.turns_ended: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    async def on_agent_start(self, agent) -> None:
        self.started = True

    def get_tools(self) -> dict:
        return self._tools

    def get_prompt_additions(self) -> str:
        return self._prompt

    async def on_turn_start(self, user_input: str) -> str:
        self.turns_started.append(user_input)
        return user_input

    async def on_turn_end(self, response: str) -> None:
        self.turns_ended.append(response)

    async def on_shutdown(self) -> None:
        self.shutdown_called = True

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        if self._slash_cmd and cmd == self._slash_cmd:
            return "handled"
        return None


# ── MiddlewareManager tests ────────────────────────────────────────

def test_collect_tools_empty():
    """Empty manager returns no tools."""
    mgr = MiddlewareManager()
    assert mgr.collect_tools() == {}


def test_collect_tools_merges():
    """Tools from multiple middleware are merged."""
    mw1 = DummyMiddleware("a", tools={"t1": {"schema": {}, "function": None}})
    mw2 = DummyMiddleware("b", tools={"t2": {"schema": {}, "function": None}})
    mgr = MiddlewareManager([mw1, mw2])

    tools = mgr.collect_tools()
    assert "t1" in tools
    assert "t2" in tools


def test_collect_tools_later_overrides():
    """Later middleware overrides earlier tools with same name."""
    mw1 = DummyMiddleware("a", tools={"t1": {"schema": {"v": 1}, "function": None}})
    mw2 = DummyMiddleware("b", tools={"t1": {"schema": {"v": 2}, "function": None}})
    mgr = MiddlewareManager([mw1, mw2])

    tools = mgr.collect_tools()
    assert tools["t1"]["schema"]["v"] == 2


def test_build_prompt_additions():
    """Prompt additions are concatenated with double newlines."""
    mw1 = DummyMiddleware("a", prompt="Hello")
    mw2 = DummyMiddleware("b", prompt="World")
    mw3 = DummyMiddleware("c", prompt="")  # Empty should be excluded
    mgr = MiddlewareManager([mw1, mw2, mw3])

    result = mgr.build_prompt_additions()
    assert result == "Hello\n\nWorld"


def test_build_prompt_additions_empty():
    """No middleware prompt additions returns empty string."""
    mgr = MiddlewareManager()
    assert mgr.build_prompt_additions() == ""


@pytest.mark.asyncio
async def test_startup_calls_all():
    """Startup calls on_agent_start on all middleware."""
    mw1 = DummyMiddleware("a")
    mw2 = DummyMiddleware("b")
    mgr = MiddlewareManager([mw1, mw2])

    await mgr.startup(None)  # type: ignore
    assert mw1.started
    assert mw2.started


@pytest.mark.asyncio
async def test_shutdown_reverse_order():
    """Shutdown calls on_shutdown in reverse order."""
    order = []

    class OrderedMW(DummyMiddleware):
        async def on_shutdown(self) -> None:
            order.append(self._name)

    mw1 = OrderedMW("first")
    mw2 = OrderedMW("second")
    mw3 = OrderedMW("third")
    mgr = MiddlewareManager([mw1, mw2, mw3])

    await mgr.shutdown()
    assert order == ["third", "second", "first"]


@pytest.mark.asyncio
async def test_on_turn_start_chains():
    """Turn start hooks are called in order and can transform input."""

    class PrefixMW(DummyMiddleware):
        async def on_turn_start(self, user_input: str) -> str:
            return f"[{self._name}]{user_input}"

    mw1 = PrefixMW("a")
    mw2 = PrefixMW("b")
    mgr = MiddlewareManager([mw1, mw2])

    result = await mgr.on_turn_start("hello")
    assert result == "[b][a]hello"


@pytest.mark.asyncio
async def test_on_turn_end_calls_all():
    """Turn end hooks are called on all middleware."""
    mw1 = DummyMiddleware("a")
    mw2 = DummyMiddleware("b")
    mgr = MiddlewareManager([mw1, mw2])

    await mgr.on_turn_end("response")
    assert mw1.turns_ended == ["response"]
    assert mw2.turns_ended == ["response"]


@pytest.mark.asyncio
async def test_handle_slash_command_first_wins():
    """First middleware to handle a slash command wins."""
    mw1 = DummyMiddleware("a", slash_cmd="/foo")
    mw2 = DummyMiddleware("b", slash_cmd="/foo")
    mgr = MiddlewareManager([mw1, mw2])

    result = await mgr.handle_slash_command("/foo", "")
    assert result == "handled"


@pytest.mark.asyncio
async def test_handle_slash_command_unhandled():
    """Unhandled slash commands return None."""
    mw1 = DummyMiddleware("a", slash_cmd="/foo")
    mgr = MiddlewareManager([mw1])

    result = await mgr.handle_slash_command("/bar", "")
    assert result is None


def test_get_middleware_by_name():
    """Can retrieve middleware by name."""
    mw1 = DummyMiddleware("alpha")
    mw2 = DummyMiddleware("beta")
    mgr = MiddlewareManager([mw1, mw2])

    assert mgr.get("alpha") is mw1
    assert mgr.get("beta") is mw2
    assert mgr.get("gamma") is None


def test_add_middleware():
    """Can add middleware dynamically."""
    mgr = MiddlewareManager()
    mw = DummyMiddleware("late")
    mgr.add(mw)

    assert mgr.get("late") is mw
    assert len(mgr.middlewares) == 1


class MockProvider(Provider):
    def __init__(self, responses):
        self.responses = list(responses)

    @property
    def model_name(self) -> str:
        return "mock"

    async def send(self, messages, tools, system_prompt):
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_plugin_middleware_wires_runtime_hooks(tmp_path):
    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "hook-plugin"
    plugin_dir.mkdir(parents=True)
    log_file = tmp_path / "plugin.log"
    plugin_dir.joinpath("plugin.py").write_text(
        "from pathlib import Path\n"
        f"LOG = Path({str(log_file)!r})\n"
        "PLUGIN_NAME = 'Hook Plugin'\n"
        "def register(hooks):\n"
        "    async def on_start(**kwargs):\n"
        "        LOG.write_text('start\\n')\n"
        "    async def before_send(messages, tools):\n"
        "        LOG.write_text(LOG.read_text() + 'before\\n')\n"
        "    async def after_response(response):\n"
        "        LOG.write_text(LOG.read_text() + 'after\\n')\n"
        "    async def on_tool_result(tool_name, result, **kwargs):\n"
        "        LOG.write_text(LOG.read_text() + f'tool:{tool_name}\\n')\n"
        "        return f'plugin:{result}'\n"
        "    async def on_stop(**kwargs):\n"
        "        LOG.write_text(LOG.read_text() + 'stop\\n')\n"
        "    hooks.on_agent_start(on_start)\n"
        "    hooks.on_before_send(before_send)\n"
        "    hooks.on_after_response(after_response)\n"
        "    hooks.on_tool_result(on_tool_result)\n"
        "    hooks.on_agent_stop(on_stop)\n",
        encoding="utf-8",
    )

    async def echo():
        return "result"

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="t1", name="echo", input={})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="done")]),
    ])
    tools = {
        "echo": {
            "function": echo,
            "schema": {"name": "echo", "description": "", "input_schema": {}},
        }
    }
    plugin_mw = PluginMiddleware(config=AgentConfig(plugins_dirs=[str(plugin_root)]))
    mgr = MiddlewareManager([plugin_mw])
    agent = Agent(provider=provider, event_bus=EventBus(), tools=tools, middleware_manager=mgr)

    await agent.initialize()
    await agent.run("use tool")
    await mgr.shutdown()

    log = log_file.read_text(encoding="utf-8")
    assert "start" in log
    assert "before" in log
    assert "after" in log
    assert "tool:echo" in log
    assert "stop" in log
    assert "plugin:result" in str(agent.history)
