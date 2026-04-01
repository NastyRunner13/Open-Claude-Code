"""OpenAI provider — supports GPT, o-series, and any OpenAI-compatible API."""

from __future__ import annotations

import json

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    StreamEvent,
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
    """Convert Anthropic-style messages to OpenAI format."""
    converted = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        converted.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                continue

            if role == "assistant":
                text_parts = []
                tool_calls = []

                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })

                msg_dict: dict = {"role": "assistant"}
                msg_dict["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                converted.append(msg_dict)
                continue

            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
            if text_parts:
                converted.append({"role": "user", "content": "\n".join(text_parts)})

    return converted


class OpenAIProvider(Provider):
    """OpenAI provider — GPT-4o, o1, o3, and any OpenAI-compatible endpoint."""

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

    def _build_kwargs(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> dict:
        """Build the kwargs dict shared by send() and stream()."""
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

        return kwargs

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to OpenAI API and return normalized response."""
        try:
            kwargs = self._build_kwargs(messages, tools, system_prompt)
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            raise ProviderError(str(e)) from e

        choice = response.choices[0]
        message = choice.message
        content: list[TextBlock | ToolUseBlock] = []

        thinking: ThinkingBlock | None = None
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking = ThinkingBlock(
                thinking=message.reasoning_content,
                signature="",
            )

        if message.content:
            content.append(TextBlock(text=message.content))

        if message.tool_calls:
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

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response tokens from OpenAI using server-sent events."""
        try:
            kwargs = self._build_kwargs(messages, tools, system_prompt)
            kwargs["stream"] = True
            response = await self.client.chat.completions.create(**kwargs)
        except Exception as e:
            raise ProviderError(str(e)) from e

        text_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}

        try:
            async for chunk in response:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if delta.content:
                    text_parts.append(delta.content)
                    yield StreamEvent(type="text_delta", text=delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc_delta.id or "",
                                "name": "",
                                "arguments": "",
                            }
                            if tc_delta.function and tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                                yield StreamEvent(
                                    type="tool_use_start",
                                    tool_name=tc_delta.function.name,
                                    tool_id=tc_delta.id or "",
                                )

                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments
                                yield StreamEvent(
                                    type="input_json_delta",
                                    text=tc_delta.function.arguments,
                                )

        except Exception as e:
            raise ProviderError(str(e)) from e

        content: list[TextBlock | ToolUseBlock] = []
        full_text = "".join(text_parts)
        if full_text:
            content.append(TextBlock(text=full_text))

        for tc_data in tool_calls_acc.values():
            try:
                args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
            except json.JSONDecodeError:
                args = {"raw": tc_data["arguments"]}

            content.append(ToolUseBlock(
                id=tc_data["id"],
                name=tc_data["name"],
                input=args,
            ))
            yield StreamEvent(
                type="tool_use_end",
                tool_name=tc_data["name"],
                tool_id=tc_data["id"],
                tool_input=args,
            )

        yield StreamEvent(
            type="done",
            response=ProviderResponse(thinking=None, content=content),
        )
