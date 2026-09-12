"""Provider registry — auto-detection and factory.

Resolves model strings to the correct provider:
  claude-*     → AnthropicProvider
  gpt-* / o1-* / o3-* → OpenAIProvider
  gemini-*     → GeminiProvider
  groq/*       → GroqProvider (prefix required; llama-* is not Groq)
  ollama/*     → OllamaProvider
  openrouter/* → OpenRouterProvider
  vendor/model + OPENROUTER_API_KEY → OpenRouterProvider
  base_url     → OpenAIProvider (custom endpoint)
"""

from __future__ import annotations

import os

from .base import Provider, ProviderError


def create_provider(
    model: str,
    max_tokens: int = 16000,
    api_key: str | None = None,
    base_url: str | None = None,
    prompt_caching: bool = True,
) -> Provider:
    """Create the appropriate provider based on model name.

    Auto-detects the provider from the model string.
    Supports explicit prefixes: groq/, ollama/, openrouter/.
    Groq is prefix-only: unprefixed llama- / mixtral- / gemma- / deepseek-
    names are not stolen when GROQ_API_KEY is set.
    Falls back to OpenAI-compatible if a base_url is given.
    Vendor/model slugs route to OpenRouter when OPENROUTER_API_KEY is set.
    Falls back to Anthropic otherwise.
    """
    model_lower = model.lower()

    # Explicit provider prefixes
    if model_lower.startswith("groq/"):
        from .groq import GroqProvider
        return GroqProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    if model_lower.startswith("ollama/"):
        from .ollama import OllamaProvider
        return OllamaProvider(model=model, max_tokens=max_tokens, base_url=base_url)

    if model_lower.startswith("openrouter/"):
        from .openrouter import OpenRouterProvider
        return OpenRouterProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    # Custom endpoint → OpenAI-compatible
    if base_url:
        from .openai import OpenAIProvider
        return OpenAIProvider(
            model=model, max_tokens=max_tokens, api_key=api_key, base_url=base_url,
        )

    # Model name prefix detection
    if model_lower.startswith("claude"):
        from .anthropic import AnthropicProvider
        return AnthropicProvider(
            model=model, max_tokens=max_tokens, api_key=api_key,
            prompt_caching=prompt_caching,
        )

    if any(model_lower.startswith(p) for p in ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        from .openai import OpenAIProvider
        return OpenAIProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    if model_lower.startswith("gemini"):
        from .gemini import GeminiProvider
        return GeminiProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    # vendor/model slugs (Together, Fireworks, xAI, OpenRouter catalog ids)
    if "/" in model_lower and os.environ.get("OPENROUTER_API_KEY"):
        from .openrouter import OpenRouterProvider
        return OpenRouterProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    # Default → Anthropic
    from .anthropic import AnthropicProvider
    return AnthropicProvider(
        model=model, max_tokens=max_tokens, api_key=api_key,
        prompt_caching=prompt_caching,
    )
