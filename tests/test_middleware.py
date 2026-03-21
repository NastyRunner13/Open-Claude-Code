"""Tests for the middleware architecture."""

import asyncio

import pytest

from open_claude_code.middleware import Middleware, MiddlewareManager


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
