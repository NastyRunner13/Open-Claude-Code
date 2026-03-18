"""Ollama provider — run local models via Ollama.

Ollama exposes an OpenAI-compatible API at localhost:11434/v1,
so this wraps the OpenAI provider with Ollama-specific defaults.
"""

from __future__ import annotations

from .base import Provider, ProviderError, ProviderResponse
from .openai import OpenAIProvider


# Default Ollama endpoint
_DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(Provider):
    """Ollama provider — local model inference via OpenAI-compatible API."""

    def __init__(
        self,
        model: str = "llama3.2",
        max_tokens: int = 16000,
        base_url: str | None = None,
    ) -> None:
        # Strip "ollama/" prefix if present (e.g., "ollama/llama3.2")
        if model.startswith("ollama/"):
            model = model[7:]

        self.model = model
        self.max_tokens = max_tokens

        # Ollama doesn't need an API key — use dummy
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
