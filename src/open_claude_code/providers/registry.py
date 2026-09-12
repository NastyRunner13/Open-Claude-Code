"""Provider registry — auto-detection and factory.

Resolves model strings to the correct provider:
  claude-*     → AnthropicProvider
  gpt-* / o1-* / o3-* → OpenAIProvider
  gemini-*     → GeminiProvider
  groq/*       → GroqProvider (prefix required; llama-* is not Groq)
  ollama/*     → OllamaProvider (native /api/chat)
  openrouter/* → OpenRouterProvider
  vendor/model + OPENROUTER_API_KEY → OpenRouterProvider
  base_url     → OpenAIProvider (custom endpoint)
"""

from __future__ import annotations

import os

from .base import Provider


def resolve_provider(model: str, base_url: str | None = None) -> str:
    """Return the provider id a model string maps to, without constructing a client.

    Same routing as create_provider(): prefixes, then base_url, then name
    heuristics. Groq is prefix-only. Vendor/model slugs go to OpenRouter only
    when OPENROUTER_API_KEY is set. Unknown names default to Anthropic.
    """
    model_lower = model.lower()
    if model_lower.startswith("groq/"):
        return "groq"
    if model_lower.startswith("ollama/"):
        return "ollama"
    if model_lower.startswith("openrouter/"):
        return "openrouter"
    if base_url:
        return "openai-compat"
    if model_lower.startswith("claude"):
        return "anthropic"
    if any(model_lower.startswith(p) for p in ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return "openai"
    if model_lower.startswith("gemini"):
        return "gemini"
    if "/" in model_lower and os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return "anthropic"


def create_provider(
    model: str,
    max_tokens: int = 16000,
    api_key: str | None = None,
    base_url: str | None = None,
    prompt_caching: bool = True,
    num_ctx: int | None = None,
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
    kind = resolve_provider(model, base_url)

    if kind == "groq":
        from .groq import GroqProvider
        return GroqProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    if kind == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(
            model=model, max_tokens=max_tokens, base_url=base_url, num_ctx=num_ctx,
        )

    if kind == "openrouter":
        from .openrouter import OpenRouterProvider
        return OpenRouterProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    if kind == "openai-compat":
        from .openai import OpenAIProvider
        return OpenAIProvider(
            model=model, max_tokens=max_tokens, api_key=api_key, base_url=base_url,
        )

    if kind == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    if kind == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(model=model, max_tokens=max_tokens, api_key=api_key)

    from .anthropic import AnthropicProvider
    return AnthropicProvider(
        model=model, max_tokens=max_tokens, api_key=api_key,
        prompt_caching=prompt_caching,
    )
