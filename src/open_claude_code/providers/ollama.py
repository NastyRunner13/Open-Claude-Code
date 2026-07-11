"""Ollama provider — run local models via Ollama.

Ollama exposes an OpenAI-compatible API at localhost:11434/v1,
so this wraps the OpenAI provider with Ollama-specific defaults.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .base import Provider, ProviderResponse, StreamEvent
from .openai import OpenAIProvider


_DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(Provider):
    """Ollama provider — local model inference via OpenAI-compatible API."""

    def __init__(
        self,
        model: str = "llama3.2",
        max_tokens: int = 16000,
        base_url: str | None = None,
    ) -> None:
        if model.startswith("ollama/"):
            model = model[7:]

        self.model = model
        self.max_tokens = max_tokens

        self._inner = OpenAIProvider(
            model=model,
            max_tokens=max_tokens,
            api_key="ollama",
            base_url=base_url or _DEFAULT_BASE_URL,
        )

    @property
    def model_name(self) -> str:
        return f"ollama/{self.model}"

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
