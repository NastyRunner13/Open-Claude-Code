"""Provider interface and shared types."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


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
class StreamEvent:
    """A single event from a streaming LLM response.

    Event types:
      - text_delta:       Incremental text token
      - thinking_delta:   Incremental thinking/reasoning token
      - tool_use_start:   Tool call started (has name/id)
      - input_json_delta: Incremental tool input JSON
      - tool_use_end:     Tool call input is complete
      - done:             Stream finished, full response is in `response`
    """
    type: str
    text: str = ""
    tool_name: str = ""
    tool_id: str = ""
    tool_input: dict = field(default_factory=dict)
    thinking_signature: str = ""
    response: "ProviderResponse | None" = None


@dataclass
class ProviderResponse:
    """Normalized response from an LLM provider."""
    thinking: ThinkingBlock | None
    content: list[ContentBlock]


class ProviderError(Exception):
    """Raised when a provider call fails."""


class Provider(ABC):
    """Abstract interface for LLM providers.

    All providers normalize their response into ProviderResponse so the
    agent loop never needs to know which LLM is being used.

    Providers must implement send() and should implement stream() for
    real-time token delivery. The default stream() falls back to send().
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
    ) -> AsyncIterator[StreamEvent]:
        """Stream response tokens from the model.

        Default implementation falls back to send() and yields a single
        done event. Providers should override for true streaming.
        """
        response = await self.send(messages, tools, system_prompt)
        # Yield text as a single delta for compat
        for block in response.content:
            if isinstance(block, TextBlock):
                yield StreamEvent(type="text_delta", text=block.text)
        yield StreamEvent(type="done", response=response)
