"""OpenRouter provider — OpenAI-compatible access to many hosted models.

Thin wrap of OpenAIProvider pointed at OpenRouter, with OPENROUTER_API_KEY
and the attribution headers OpenRouter asks for.
"""

from __future__ import annotations

import os

from collections.abc import AsyncIterator

from .base import Provider, ProviderError, ProviderResponse, StreamEvent
from .openai import OpenAIProvider


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_HEADERS = {
    "HTTP-Referer": "https://github.com/NastyRunner13/Open-Claude-Code",
    "X-Title": "Open Claude Code",
}


class OpenRouterProvider(Provider):
    """OpenRouter provider — wraps OpenAI-compatible client at OpenRouter."""

    def __init__(
        self,
        model: str = "openrouter/auto",
        max_tokens: int = 16000,
        api_key: str | None = None,
    ) -> None:
        prefix = "openrouter/"
        if model.lower().startswith(prefix):
            model = model[len(prefix):]

        self.model = model
        self.max_tokens = max_tokens
        self.default_headers = dict(DEFAULT_HEADERS)

        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "OpenRouter API key not found. Set OPENROUTER_API_KEY "
                "environment variable or pass --api-key."
            )

        self._inner = OpenAIProvider(
            model=model,
            max_tokens=max_tokens,
            api_key=resolved_key,
            base_url=DEFAULT_BASE_URL,
            default_headers=self.default_headers,
        )

    @property
    def model_name(self) -> str:
        return f"openrouter/{self.model}"

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Delegate to the inner OpenAI-compatible provider."""
        return await self._inner.send(messages, tools, system_prompt)

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Delegate streaming to the inner OpenAI-compatible provider."""
        async for event in self._inner.stream(messages, tools, system_prompt):
            yield event
