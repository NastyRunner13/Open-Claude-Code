"""Anthropic API provider implementation with extended thinking support."""

from anthropic import AsyncAnthropic

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


class AnthropicProvider(Provider):
    """Anthropic Claude provider with extended thinking."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 16000,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = AsyncAnthropic(api_key=api_key)

    @property
    def model_name(self) -> str:
        return self.model

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to Anthropic API and return normalized response."""
        try:
            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system_prompt,
                "messages": messages,
            }

            # Enable extended thinking if model supports it
            if "claude" in self.model:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": max(self.max_tokens // 2, 1024),
                }

            if tools:
                kwargs["tools"] = tools

            response = await self.client.messages.create(**kwargs)

        except Exception as e:
            raise ProviderError(str(e)) from e

        thinking: ThinkingBlock | None = None
        content: list[TextBlock | ToolUseBlock] = []

        for block in response.content:
            if block.type == "thinking":
                thinking = ThinkingBlock(
                    thinking=block.thinking,
                    signature=block.signature,
                )
            elif block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(
                    ToolUseBlock(id=block.id, name=block.name, input=block.input)
                )

        return ProviderResponse(thinking=thinking, content=content)
