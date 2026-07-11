"""Groq provider — fast inference via Groq cloud.

Groq uses the OpenAI-compatible API format, so this is a thin wrapper
around the OpenAI provider with Groq-specific defaults.
"""

from __future__ import annotations

import os

from collections.abc import AsyncIterator

from .base import Provider, ProviderError, ProviderResponse, StreamEvent
from .openai import OpenAIProvider


class GroqProvider(Provider):
    """Groq provider — wraps OpenAI-compatible client pointed at Groq's API."""

    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        max_tokens: int = 16000,
        api_key: str | None = None,
    ) -> None:
        if model.startswith("groq/"):
            model = model[5:]

        self.model = model
        self.max_tokens = max_tokens

        resolved_key = api_key or os.environ.get("GROQ_API_KEY")
        if not resolved_key:
            raise ProviderError(
                "Groq API key not found. Set GROQ_API_KEY environment variable "
                "or pass --api-key."
            )

        self._inner = OpenAIProvider(
            model=model,
            max_tokens=max_tokens,
            api_key=resolved_key,
            base_url="https://api.groq.com/openai/v1",
        )

    @property
    def model_name(self) -> str:
        return f"groq/{self.model}"

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
