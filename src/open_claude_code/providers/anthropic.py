"""Anthropic API provider with extended thinking and prompt caching.

Prompt caching uses cache_control markers on system prompt content blocks
to cache static parts of the prompt. This reduces costs by up to 90% on
cached input tokens and improves latency by up to 85%.
"""

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    StreamEvent,
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
        """Build system prompt with cache control markers."""
        if not self.prompt_caching:
            return system_prompt

        parts = system_prompt.split("\n\n## ", 1)
        blocks = []

        base_prompt = parts[0].strip()
        if base_prompt:
            blocks.append({
                "type": "text",
                "text": base_prompt,
                "cache_control": {"type": "ephemeral"},
            })

        if len(parts) > 1:
            additions = "## " + parts[1]
            blocks.append({
                "type": "text",
                "text": additions,
            })

        return blocks if blocks else system_prompt

    def _add_message_caching(self, messages: list[dict]) -> list[dict]:
        """Add cache control to early conversation messages."""
        if not self.prompt_caching or len(messages) < 2:
            return messages

        cached = []
        cache_points = 0
        max_cache_points = 2

        for i, msg in enumerate(messages):
            new_msg = dict(msg)

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
                    new_content = list(content)
                    last_block = dict(new_content[-1])
                    if last_block.get("type") in ("text", "tool_result") and "cache_control" not in last_block:
                        last_block["cache_control"] = {"type": "ephemeral"}
                        new_content[-1] = last_block
                        new_msg["content"] = new_content
                        cache_points += 1

            cached.append(new_msg)

        return cached

    def _build_kwargs(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> dict:
        """Build the kwargs dict shared by send() and stream()."""
        system = self._build_system_blocks(system_prompt)
        cached_messages = self._add_message_caching(messages)

        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": cached_messages,
        }

        if "claude" in self.model:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": max(self.max_tokens // 2, 1024),
            }

        if tools:
            if self.prompt_caching and tools:
                cached_tools = list(tools)
                if cached_tools:
                    last_tool = dict(cached_tools[-1])
                    last_tool["cache_control"] = {"type": "ephemeral"}
                    cached_tools[-1] = last_tool
                kwargs["tools"] = cached_tools
            else:
                kwargs["tools"] = tools

        return kwargs

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to Anthropic API with prompt caching support."""
        try:
            kwargs = self._build_kwargs(messages, tools, system_prompt)
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

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response tokens from Anthropic using server-sent events."""
        try:
            kwargs = self._build_kwargs(messages, tools, system_prompt)
        except Exception as e:
            raise ProviderError(str(e)) from e

        # Accumulators for building the final ProviderResponse
        thinking_text = ""
        thinking_signature = ""
        text_parts: list[str] = []
        tool_blocks: list[ToolUseBlock] = []
        current_tool_name = ""
        current_tool_id = ""
        current_tool_json = ""

        try:
            async with self.client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    event_type = getattr(event, "type", "")

                    if event_type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            current_tool_name = block.name
                            current_tool_id = block.id
                            current_tool_json = ""
                            yield StreamEvent(
                                type="tool_use_start",
                                tool_name=block.name,
                                tool_id=block.id,
                            )

                    elif event_type == "content_block_delta":
                        delta = event.delta
                        delta_type = getattr(delta, "type", "")

                        if delta_type == "text_delta":
                            text = delta.text
                            text_parts.append(text)
                            yield StreamEvent(type="text_delta", text=text)

                        elif delta_type == "thinking_delta":
                            text = delta.thinking
                            thinking_text += text
                            yield StreamEvent(type="thinking_delta", text=text)

                        elif delta_type == "input_json_delta":
                            current_tool_json += delta.partial_json
                            yield StreamEvent(
                                type="input_json_delta",
                                text=delta.partial_json,
                            )

                        elif delta_type == "signature_delta":
                            thinking_signature = delta.signature

                    elif event_type == "content_block_stop":
                        if current_tool_name:
                            import json
                            try:
                                tool_input = json.loads(current_tool_json) if current_tool_json else {}
                            except json.JSONDecodeError:
                                tool_input = {"raw": current_tool_json}

                            tool_blocks.append(ToolUseBlock(
                                id=current_tool_id,
                                name=current_tool_name,
                                input=tool_input,
                            ))
                            yield StreamEvent(
                                type="tool_use_end",
                                tool_name=current_tool_name,
                                tool_id=current_tool_id,
                                tool_input=tool_input,
                            )
                            current_tool_name = ""
                            current_tool_id = ""
                            current_tool_json = ""

        except Exception as e:
            raise ProviderError(str(e)) from e

        # Build final response
        thinking_block = None
        if thinking_text:
            thinking_block = ThinkingBlock(
                thinking=thinking_text,
                signature=thinking_signature,
            )

        content: list[TextBlock | ToolUseBlock] = []
        full_text = "".join(text_parts)
        if full_text:
            content.append(TextBlock(text=full_text))
        content.extend(tool_blocks)

        yield StreamEvent(
            type="done",
            response=ProviderResponse(thinking=thinking_block, content=content),
        )
