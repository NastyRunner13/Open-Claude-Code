"""Tests for streaming response support."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_claude_code.providers.base import (
    Provider,
    ProviderResponse,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from open_claude_code.events import (
    EventBus,
    StreamStart,
    StreamTextDelta,
    StreamThinkingDelta,
    StreamEnd,
    Stop,
)


# ── StreamEvent tests ──────────────────────────────────────────────

class TestStreamEvent:
    """Tests for the StreamEvent dataclass."""

    def test_text_delta(self):
        evt = StreamEvent(type="text_delta", text="hello")
        assert evt.type == "text_delta"
        assert evt.text == "hello"
        assert evt.tool_name == ""

    def test_thinking_delta(self):
        evt = StreamEvent(type="thinking_delta", text="reasoning...")
        assert evt.type == "thinking_delta"
        assert evt.text == "reasoning..."

    def test_tool_use_start(self):
        evt = StreamEvent(
            type="tool_use_start",
            tool_name="read_file",
            tool_id="tool_123",
        )
        assert evt.type == "tool_use_start"
        assert evt.tool_name == "read_file"
        assert evt.tool_id == "tool_123"

    def test_tool_use_end(self):
        evt = StreamEvent(
            type="tool_use_end",
            tool_name="read_file",
            tool_id="tool_123",
            tool_input={"file_path": "/foo.py"},
        )
        assert evt.type == "tool_use_end"
        assert evt.tool_input == {"file_path": "/foo.py"}

    def test_done(self):
        resp = ProviderResponse(
            thinking=None,
            content=[TextBlock(text="final answer")],
        )
        evt = StreamEvent(type="done", response=resp)
        assert evt.type == "done"
        assert evt.response is resp

    def test_defaults(self):
        evt = StreamEvent(type="text_delta")
        assert evt.text == ""
        assert evt.tool_name == ""
        assert evt.tool_id == ""
        assert evt.tool_input == {}
        assert evt.response is None


# ── Provider.stream() default fallback ─────────────────────────────

class TestProviderStreamFallback:
    """Test the default stream() which falls back to send()."""

    @pytest.mark.asyncio
    async def test_default_stream_yields_text_and_done(self):
        """The base Provider.stream() should yield text deltas then done."""

        class MockProvider(Provider):
            @property
            def model_name(self) -> str:
                return "mock"

            async def send(self, messages, tools, system_prompt):
                return ProviderResponse(
                    thinking=None,
                    content=[TextBlock(text="Hello world")],
                )

        provider = MockProvider()
        events = []
        async for evt in provider.stream([], [], "system"):
            events.append(evt)

        assert len(events) == 2
        assert events[0].type == "text_delta"
        assert events[0].text == "Hello world"
        assert events[1].type == "done"
        assert events[1].response is not None
        assert events[1].response.content[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_default_stream_with_tool_use(self):
        """Default stream should yield done with tool use blocks."""

        class MockProvider(Provider):
            @property
            def model_name(self) -> str:
                return "mock"

            async def send(self, messages, tools, system_prompt):
                return ProviderResponse(
                    thinking=None,
                    content=[
                        ToolUseBlock(id="t1", name="read_file", input={"path": "x"}),
                    ],
                )

        provider = MockProvider()
        events = []
        async for evt in provider.stream([], [], "system"):
            events.append(evt)

        # No text_delta for tool-only response, just done
        assert len(events) == 1
        assert events[0].type == "done"
        assert len(events[0].response.content) == 1
        assert events[0].response.content[0].name == "read_file"


# ── Streaming event types ──────────────────────────────────────────

class TestStreamingEventTypes:
    """Tests for the streaming event types in events/types.py."""

    def test_stream_start(self):
        from open_claude_code.events.types import StreamStart
        evt = StreamStart()
        assert evt is not None

    def test_stream_text_delta(self):
        from open_claude_code.events.types import StreamTextDelta
        evt = StreamTextDelta(text="token")
        assert evt.text == "token"

    def test_stream_thinking_delta(self):
        from open_claude_code.events.types import StreamThinkingDelta
        evt = StreamThinkingDelta(text="thought")
        assert evt.text == "thought"

    def test_stream_end(self):
        from open_claude_code.events.types import StreamEnd
        evt = StreamEnd(full_text="final response text")
        assert evt.full_text == "final response text"


# ── Event bus integration ──────────────────────────────────────────

class TestStreamingEventBus:
    """Tests that streaming events flow through the EventBus."""

    @pytest.mark.asyncio
    async def test_stream_events_emitted(self):
        """Streaming events should be emitted through the EventBus."""
        bus = EventBus()
        received = []

        async def on_stream_start(event):
            received.append(("start", event))

        async def on_text_delta(event):
            received.append(("delta", event.text))

        async def on_stream_end(event):
            received.append(("end", event.full_text))

        bus.on(StreamStart, on_stream_start)
        bus.on(StreamTextDelta, on_text_delta)
        bus.on(StreamEnd, on_stream_end)

        await bus.emit(StreamStart())
        await bus.emit(StreamTextDelta(text="Hello"))
        await bus.emit(StreamTextDelta(text=" world"))
        await bus.emit(StreamEnd(full_text="Hello world"))

        assert len(received) == 4
        assert received[0][0] == "start"
        assert received[1] == ("delta", "Hello")
        assert received[2] == ("delta", " world")
        assert received[3] == ("end", "Hello world")


# ── Agent.run_streaming() ──────────────────────────────────────────

class TestAgentRunStreaming:
    """Tests for the Agent.run_streaming() method."""

    @pytest.mark.asyncio
    async def test_run_streaming_emits_events(self):
        """run_streaming should emit StreamStart, StreamTextDelta, StreamEnd, Stop."""
        from open_claude_code.agent import Agent

        # Create a mock provider that streams text
        mock_provider = MagicMock()
        mock_provider.model_name = "mock-model"

        async def mock_stream(messages, tools, system_prompt):
            yield StreamEvent(type="text_delta", text="Hi ")
            yield StreamEvent(type="text_delta", text="there!")
            yield StreamEvent(
                type="done",
                response=ProviderResponse(
                    thinking=None,
                    content=[TextBlock(text="Hi there!")],
                ),
            )

        mock_provider.stream = mock_stream

        bus = EventBus()
        events_received = []

        async def capture(event):
            events_received.append(type(event).__name__)

        bus.on(StreamStart, capture)
        bus.on(StreamTextDelta, capture)
        bus.on(StreamEnd, capture)
        bus.on(Stop, capture)

        agent = Agent(provider=mock_provider, event_bus=bus)
        result = await agent.run_streaming("test")

        assert result == "Hi there!"
        assert "StreamStart" in events_received
        assert events_received.count("StreamTextDelta") == 2
        assert "StreamEnd" in events_received
        assert "Stop" in events_received

    @pytest.mark.asyncio
    async def test_run_streaming_fallback_on_error(self):
        """If streaming fails, run_streaming should fall back to run()."""
        from open_claude_code.agent import Agent

        mock_provider = MagicMock()
        mock_provider.model_name = "mock-model"

        async def mock_stream_fail(messages, tools, system_prompt):
            raise RuntimeError("streaming not supported")
            # Make it an async generator that raises
            yield  # pragma: no cover

        mock_provider.stream = mock_stream_fail

        # send() should work as fallback
        mock_provider.send = AsyncMock(return_value=ProviderResponse(
            thinking=None,
            content=[TextBlock(text="Fallback response")],
        ))

        bus = EventBus()
        agent = Agent(provider=mock_provider, event_bus=bus)
        result = await agent.run_streaming("test")

        assert result == "Fallback response"
