"""Tests for the event bus and lifecycle events."""

import asyncio

from open_claude_code.events import EventBus, PostToolUse, PreToolUse, Stop, Thinking


def test_emit_calls_listener():
    events = []

    async def listener(event):
        events.append(event)

    bus = EventBus()
    bus.on(Stop, listener)
    asyncio.run(bus.emit(Stop(text="hello")))

    assert len(events) == 1
    assert events[0].text == "hello"


def test_emit_multiple_listeners():
    order = []

    async def first(event):
        order.append("first")

    async def second(event):
        order.append("second")

    bus = EventBus()
    bus.on(Stop, first)
    bus.on(Stop, second)
    asyncio.run(bus.emit(Stop(text="test")))

    assert order == ["first", "second"]


def test_emit_no_listeners():
    bus = EventBus()
    asyncio.run(bus.emit(Stop(text="test")))  # should not raise


def test_approval_default_true():
    bus = EventBus()
    result = asyncio.run(bus.emit_approval(PreToolUse(tool_name="test", tool_params={})))
    assert result is True


def test_approval_approved():
    async def approve(event):
        return True

    bus = EventBus()
    bus.on_approval(approve)
    result = asyncio.run(bus.emit_approval(PreToolUse(tool_name="test", tool_params={})))
    assert result is True


def test_approval_denied():
    async def deny(event):
        return False

    bus = EventBus()
    bus.on_approval(deny)
    result = asyncio.run(bus.emit_approval(PreToolUse(tool_name="test", tool_params={})))
    assert result is False


def test_auto_approve_when_not_required():
    """Tools that don't require approval should auto-approve even if handler denies."""
    async def deny(event):
        return False

    bus = EventBus()
    bus.on_approval(deny)
    result = asyncio.run(bus.emit_approval(
        PreToolUse(tool_name="read_file", tool_params={}, requires_approval=False)
    ))
    assert result is True


def test_thinking_event():
    events = []

    async def listener(event):
        events.append(event)

    bus = EventBus()
    bus.on(Thinking, listener)
    asyncio.run(bus.emit(Thinking(text="Let me think...")))

    assert len(events) == 1
    assert events[0].text == "Let me think..."


def test_different_event_types_isolated():
    stop_events = []
    post_events = []

    async def stop_listener(event):
        stop_events.append(event)

    async def post_listener(event):
        post_events.append(event)

    bus = EventBus()
    bus.on(Stop, stop_listener)
    bus.on(PostToolUse, post_listener)

    asyncio.run(bus.emit(Stop(text="done")))
    asyncio.run(bus.emit(PostToolUse(tool_name="read_file", result="contents")))

    assert len(stop_events) == 1
    assert len(post_events) == 1
