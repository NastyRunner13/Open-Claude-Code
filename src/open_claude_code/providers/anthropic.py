"""Anthropic API provider with extended thinking and prompt caching.

Prompt caching uses cache_control markers on system prompt content blocks
to cache static parts of the prompt. This reduces costs by up to 90% on
cached input tokens and improves latency by up to 85%.
"""

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
    """Anthropic Claude provider with extended thinking and prompt caching."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 16000,
        api_key: str | None = None,
        prompt_caching: bool = True,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.client = AsyncAnthropic(api_key=api_key)
        self.prompt_caching = prompt_caching

    @property
    def model_name(self) -> str:
        return self.model

    def _build_system_blocks(self, system_prompt: str) -> list[dict] | str:
        """Build system prompt with cache control markers.

        When prompt caching is enabled, the system prompt is split into
        a stable base (cached) and dynamic additions (not cached).
        The cache_control marker tells Anthropic to cache everything
        up to and including that block.

        Returns a list of content blocks for caching, or a plain string
        if caching is disabled.
        """
        if not self.prompt_caching:
            return system_prompt

        # Split on the middleware additions boundary
        # The base prompt (before ## Project Memory, ## Current Plan, etc.)
        # is stable and should be cached. Dynamic additions change per turn.
        parts = system_prompt.split("\n\n## ", 1)

        blocks = []

        # Base system prompt — this is stable and should be cached
        base_prompt = parts[0].strip()
        if base_prompt:
            blocks.append({
                "type": "text",
                "text": base_prompt,
                "cache_control": {"type": "ephemeral"},
            })

        # Dynamic additions (middleware-injected) — not cached
        if len(parts) > 1:
            additions = "## " + parts[1]
            blocks.append({
                "type": "text",
                "text": additions,
            })

        return blocks if blocks else system_prompt

    def _add_message_caching(self, messages: list[dict]) -> list[dict]:
        """Add cache control to early conversation messages.

        The first user message often contains important context that doesn't
        change. Caching it avoids reprocessing on subsequent turns.

        We only cache messages from the first few turns to avoid excessive
        cache writes. Returns a new list (does not modify original).
        """
        if not self.prompt_caching or len(messages) < 2:
            return messages

        # Deep copy to avoid modifying the original history
        cached = []
        cache_points = 0
        max_cache_points = 2  # Anthropic allows up to 4, we use 2 for messages

        for i, msg in enumerate(messages):
            new_msg = dict(msg)

            # Cache the first user message and first assistant message
            if cache_points < max_cache_points and i < 4:
                content = new_msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    new_msg["content"] = [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                    cache_points += 1
                elif isinstance(content, list) and content:
                    # Add cache_control to the last block in the content list
                    new_content = list(content)
                    last_block = dict(new_content[-1])
                    if last_block.get("type") in ("text", "tool_result") and "cache_control" not in last_block:
                        last_block["cache_control"] = {"type": "ephemeral"}
                        new_content[-1] = last_block
                        new_msg["content"] = new_content
                        cache_points += 1

            cached.append(new_msg)

        return cached

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to Anthropic API with prompt caching support."""
        try:
            # Build system prompt with cache control
            system = self._build_system_blocks(system_prompt)

            # Add caching to early messages
            cached_messages = self._add_message_caching(messages)

            kwargs: dict = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": cached_messages,
            }

            # Enable extended thinking if model supports it
            if "claude" in self.model:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": max(self.max_tokens // 2, 1024),
                }

            if tools:
                # Add cache_control to tool definitions (they're stable)
                if self.prompt_caching and tools:
                    cached_tools = list(tools)
                    if cached_tools:
                        # Cache the last tool definition (caches all tools as a prefix)
                        last_tool = dict(cached_tools[-1])
                        last_tool["cache_control"] = {"type": "ephemeral"}
                        cached_tools[-1] = last_tool
                    kwargs["tools"] = cached_tools
                else:
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
