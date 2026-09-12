"""Scripted LLM provider for exercising the agent loop without a live API.

Use this instead of ad-hoc MockProvider subclasses when a test needs to
drive text, tools, deny, multi-tool, streaming, spawn, or 429-retry.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from open_claude_code.providers.base import (
    Provider,
    ProviderError,
    ProviderMetadata,
    ProviderResponse,
    ProviderUsage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    TransientProviderError,
)


@dataclass
class ScriptedTurn:
    """One provider round-trip. Set `error` to raise instead of answering."""

    text: str = ""
    tool_calls: tuple[ToolUseBlock, ...] = ()
    error: BaseException | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    thinking: str = ""

    @classmethod
    def reply(cls, text: str, *, input_tokens: int = 3, output_tokens: int = 2) -> ScriptedTurn:
        return cls(text=text, usage=ProviderUsage(input_tokens=input_tokens, output_tokens=output_tokens))

    @classmethod
    def tools(cls, *calls: ToolUseBlock, text: str = "") -> ScriptedTurn:
        return cls(text=text, tool_calls=calls)

    @classmethod
    def rate_limit(cls, message: str = "rate limited") -> ScriptedTurn:
        return cls(error=TransientProviderError(message, status_code=429))


class ScriptedProvider(Provider):
    """Plays a fixed list of turns for send() and stream()."""

    def __init__(self, turns: Sequence[ScriptedTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[list[dict], list[dict], str]] = []

    @property
    def model_name(self) -> str:
        return "scripted-model"

    @property
    def remaining(self) -> int:
        return len(self._turns)

    def _next(self) -> ScriptedTurn:
        if not self._turns:
            raise ProviderError("ScriptedProvider exhausted: no turns left")
        return self._turns.pop(0)

    def _record(self, messages: list[dict], tools: list[dict], system_prompt: str) -> ScriptedTurn:
        self.calls.append((messages, tools, system_prompt))
        turn = self._next()
        if turn.error is not None:
            raise turn.error
        return turn

    def _response(self, turn: ScriptedTurn) -> ProviderResponse:
        content: list[TextBlock | ToolUseBlock] = []
        if turn.text:
            content.append(TextBlock(text=turn.text))
        content.extend(turn.tool_calls)
        thinking = None
        if turn.thinking:
            thinking = ThinkingBlock(thinking=turn.thinking, signature="")
        return ProviderResponse(
            thinking=thinking,
            content=content,
            usage=turn.usage,
            metadata=ProviderMetadata(model=self.model_name, finish_reason="stop"),
        )

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        return self._response(self._record(messages, tools, system_prompt))

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        turn = self._record(messages, tools, system_prompt)
        if turn.thinking:
            yield StreamEvent(type="thinking_delta", text=turn.thinking)
        for chunk in _text_chunks(turn.text):
            yield StreamEvent(type="text_delta", text=chunk)
        for block in turn.tool_calls:
            yield StreamEvent(type="tool_use_start", tool_name=block.name, tool_id=block.id)
            yield StreamEvent(
                type="tool_use_end",
                tool_name=block.name,
                tool_id=block.id,
                tool_input=block.input,
            )
        yield StreamEvent(type="done", response=self._response(turn))


def _text_chunks(text: str) -> list[str]:
    if not text:
        return []
    parts = text.split(" ")
    return [part if i == 0 else f" {part}" for i, part in enumerate(parts)]
