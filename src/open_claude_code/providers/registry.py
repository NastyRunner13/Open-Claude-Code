"""Provider registry — auto-detection and factory."""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Provider, ProviderError


# Model prefix → provider class mapping
_PROVIDER_MAP: dict[str, type[Provider]] = {
    "claude": AnthropicProvider,
    # Future: "gpt" → OpenAIProvider, "gemini" → GeminiProvider, etc.
}


def create_provider(
    model: str,
    max_tokens: int = 16000,
    api_key: str | None = None,
    base_url: str | None = None,
) -> Provider:
    """Create the appropriate provider instance based on model name.

    Auto-detects the provider from the model string prefix.
    Falls back to Anthropic if no match is found.
    """
    # Check known prefixes
    for prefix, provider_cls in _PROVIDER_MAP.items():
        if model.startswith(prefix):
            return provider_cls(model=model, max_tokens=max_tokens, api_key=api_key)

    # Default to Anthropic for now
    return AnthropicProvider(model=model, max_tokens=max_tokens, api_key=api_key)
