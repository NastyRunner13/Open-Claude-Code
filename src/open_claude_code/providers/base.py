"""Provider interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import monotonic
from typing import AsyncIterator, Literal


@dataclass
class TextBlock:
    """A text content block from the model response."""
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    """A tool_use content block from the model response."""
    id: str
    name: str
    input: dict
    type: str = "tool_use"


ContentBlock = TextBlock | ToolUseBlock


@dataclass
class ThinkingBlock:
    """A thinking/reasoning block from the model response."""
    thinking: str
    signature: str
    type: str = "thinking"


@dataclass
class ProviderResponse:
    """Normalized response from an LLM provider."""
    thinking: ThinkingBlock | None
    content: list[ContentBlock]
    usage: "ProviderUsage" = field(default_factory=lambda: ProviderUsage())
    metadata: "ProviderMetadata" = field(default_factory=lambda: ProviderMetadata())


@dataclass
class ProviderUsage:
    """Normalized provider token accounting, including cache fields when known."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ProviderMetadata:
    """Provider metadata useful for support, tracing, and UI status."""

    request_id: str = ""
    finish_reason: str = ""
    latency_ms: float = 0.0
    model: str = ""


@dataclass
class ProviderStreamEvent:
    """A normalized event from a streaming provider response."""

    type: Literal[
        "message_start", "content_delta", "thinking_delta", "tool_call_delta",
        "tool_call_complete", "usage_delta", "message_complete", "error",
    ]
    text: str = ""
    tool_call: ToolUseBlock | None = None
    usage: ProviderUsage | None = None
    metadata: ProviderMetadata | None = None
    response: ProviderResponse | None = None


class ProviderError(Exception):
    """Typed provider failure with retry-safe classification metadata."""

    def __init__(self, message: str, *, transient: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code

    @classmethod
    def from_exception(cls, error: Exception) -> "ProviderError":
        status_code = getattr(error, "status_code", None)
        transient = status_code == 429 or (isinstance(status_code, int) and status_code >= 500)
        return cls(str(error), transient=transient, status_code=status_code)


class TransientProviderError(ProviderError):
    """A provider error that may succeed on retry."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, transient=True, status_code=status_code)


class Provider(ABC):
    """Abstract interface for LLM providers.

    All providers normalize their response into ProviderResponse so the
    agent loop never needs to know which LLM is being used.
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""

    @abstractmethod
    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to the model and return a normalized response."""

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Yield a normalized stream.

        Providers that expose token streams can override this method. The
        default preserves compatibility for providers/endpoints that only have
        a one-shot API while still giving the agent a uniform consumption path.
        """
        started = monotonic()
        yield ProviderStreamEvent(type="message_start")
        try:
            response = await self.send(messages, tools, system_prompt)
        except ProviderError as error:
            yield ProviderStreamEvent(type="error", text=str(error))
            raise
        if not response.metadata.latency_ms:
            response.metadata.latency_ms = (monotonic() - started) * 1000
        if not response.metadata.model:
            response.metadata.model = self.model_name
        if response.thinking:
            yield ProviderStreamEvent(type="thinking_delta", text=response.thinking.thinking)
        for block in response.content:
            if isinstance(block, TextBlock):
                yield ProviderStreamEvent(type="content_delta", text=block.text)
            else:
                yield ProviderStreamEvent(type="tool_call_complete", tool_call=block)
        yield ProviderStreamEvent(type="usage_delta", usage=response.usage, metadata=response.metadata)
        yield ProviderStreamEvent(type="message_complete", response=response, metadata=response.metadata)
