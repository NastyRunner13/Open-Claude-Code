"""OpenAI provider — supports GPT, o-series, and any OpenAI-compatible API."""

from __future__ import annotations

import uuid

from openai import AsyncOpenAI

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool schemas to OpenAI function-calling format."""
    openai_tools = []
    for tool in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return openai_tools


def _convert_messages(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI format.

    Key differences:
      - Anthropic uses tool_result blocks in user messages; OpenAI uses role=tool messages
      - Anthropic tool_use blocks become assistant tool_calls
      - Thinking blocks are stripped (OpenAI doesn't have them in history)
    """
    converted = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            # Check if this is a tool_result message
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        converted.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                continue

            # Assistant message with possible tool_use and thinking
            if role == "assistant":
                text_parts = []
                tool_calls = []

                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            import json
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })
                        # Skip thinking blocks

                msg_dict: dict = {"role": "assistant"}
                msg_dict["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                converted.append(msg_dict)
                continue

            # User message with mixed content
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
            if text_parts:
                converted.append({"role": "user", "content": "\n".join(text_parts)})

    return converted


class OpenAIProvider(Provider):
    """OpenAI provider — GPT-4o, o1, o3, and any OpenAI-compatible endpoint.

    Also works with OpenRouter, Together AI, Fireworks, etc. by setting base_url.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        max_tokens: int = 16000,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    @property
    def model_name(self) -> str:
        return self.model

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to OpenAI API and return normalized response."""
        try:
            openai_messages = [{"role": "system", "content": system_prompt}]
            openai_messages.extend(_convert_messages(messages))

            kwargs: dict = {
                "model": self.model,
                "messages": openai_messages,
                "max_completion_tokens": self.max_tokens,
            }

            if tools:
                kwargs["tools"] = _anthropic_tools_to_openai(tools)
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)

        except Exception as e:
            raise ProviderError(str(e)) from e

        choice = response.choices[0]
        message = choice.message
        content: list[TextBlock | ToolUseBlock] = []

        # Extract reasoning/thinking if present (o1/o3 models)
        thinking: ThinkingBlock | None = None
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking = ThinkingBlock(
                thinking=message.reasoning_content,
                signature="",
            )

        # Text content
        if message.content:
            content.append(TextBlock(text=message.content))

        # Tool calls
        if message.tool_calls:
            import json
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {"raw": tc.function.arguments}

                content.append(ToolUseBlock(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        return ProviderResponse(thinking=thinking, content=content)
