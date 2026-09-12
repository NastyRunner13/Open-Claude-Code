"""OpenAI provider — supports GPT, o-series, and any OpenAI-compatible API."""

from __future__ import annotations

import json

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .base import (
    Provider,
    ProviderError,
    ProviderMetadata,
    ProviderResponse,
    ProviderUsage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from .tool_calls import apply_text_tool_recovery


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


_PARAM_REJECTION_MARKERS = (
    "unknown",
    "unsupported",
    "not supported",
    "not a valid",
    "unexpected",
    "unrecognized",
    "extra inputs",
    "invalid parameter",
)
_TOOL_REJECTION_MARKERS = (
    "tool use is not supported",
    "does not support tool",
    "does not support function",
    "function calling is not supported",
    "function calling is not enabled",
    "tools is not supported",
    "tools are not supported",
    "tool calling is not supported",
    "tool calling is not enabled",
    "does not support tools",
)


def _error_status(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


def _error_text(error: Exception) -> str:
    return str(error).lower()


def _is_param_rejection(error: Exception, param: str) -> bool:
    if _error_status(error) not in (400, 422):
        return False
    text = _error_text(error)
    if param.lower() not in text:
        return False
    return any(marker in text for marker in _PARAM_REJECTION_MARKERS)


def _is_tool_rejection(error: Exception) -> bool:
    if _error_status(error) not in (400, 422):
        return False
    return any(marker in _error_text(error) for marker in _TOOL_REJECTION_MARKERS)


class OpenAIProvider(Provider):
    """OpenAI provider — GPT-4o, o1, o3, and any OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str = "gpt-4o",
        max_tokens: int = 16000,
        api_key: str | None = None,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        if default_headers:
            kwargs["default_headers"] = default_headers
        self.client = AsyncOpenAI(**kwargs)
        # Learned per-host: older vLLM/Groq/Ollama want max_tokens; some
        # reject stream_options.include_usage. Flip on 400 and remember.
        self._token_param = "max_completion_tokens"
        self._include_usage = True

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
        }

        if tools:
            kwargs["tools"] = _anthropic_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        return kwargs

    def _compat_kwargs(self, kwargs: dict, *, stream: bool) -> dict:
        request = dict(kwargs)
        request.pop("max_tokens", None)
        request.pop("max_completion_tokens", None)
        request[self._token_param] = self.max_tokens
        if stream:
            request["stream"] = True
            if self._include_usage:
                request["stream_options"] = {"include_usage": True}
            else:
                request.pop("stream_options", None)
        return request

    def _adapt_compat(self, error: Exception, *, stream: bool) -> bool:
        """Flip remembered compat flags when the host rejects a param. True = retry."""
        adapted = False
        if _is_param_rejection(error, self._token_param):
            self._token_param = (
                "max_tokens"
                if self._token_param == "max_completion_tokens"
                else "max_completion_tokens"
            )
            adapted = True
        if stream and self._include_usage and (
            _is_param_rejection(error, "stream_options")
            or _is_param_rejection(error, "include_usage")
        ):
            self._include_usage = False
            adapted = True
        return adapted

    def _to_provider_error(self, error: Exception, *, tools: bool) -> ProviderError:
        if tools and _is_tool_rejection(error):
            return ProviderError(
                f"This model does not support tool calling ({self.model}). "
                "Use a tool-capable model, or run in ask mode.",
                status_code=_error_status(error),
            )
        return ProviderError.from_exception(error)

    async def _create(self, kwargs: dict, *, stream: bool):
        last_error: Exception | None = None
        tools_sent = bool(kwargs.get("tools"))
        for _ in range(3):
            request = self._compat_kwargs(kwargs, stream=stream)
            try:
                return await self.client.chat.completions.create(**request)
            except Exception as error:
                last_error = error
                if self._adapt_compat(error, stream=stream):
                    continue
                raise self._to_provider_error(error, tools=tools_sent) from error
        raise self._to_provider_error(
            last_error or RuntimeError("chat.completions.create failed"),
            tools=tools_sent,
        )

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to OpenAI API and return normalized response."""
        kwargs = self._build_kwargs(messages, tools, system_prompt)
        response = await self._create(kwargs, stream=False)

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

        content = apply_text_tool_recovery(content, tools)

        usage = getattr(response, "usage", None)
        return ProviderResponse(
            thinking=thinking,
            content=content,
            usage=ProviderUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                cache_read_tokens=int(
                    getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
                ),
            ),
            metadata=ProviderMetadata(
                request_id=str(getattr(response, "id", "") or ""),
                finish_reason=str(getattr(choice, "finish_reason", "") or ""),
                model=str(getattr(response, "model", self.model) or self.model),
            ),
        )

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response tokens from OpenAI using server-sent events."""
        kwargs = self._build_kwargs(messages, tools, system_prompt)
        response = await self._create(kwargs, stream=True)

        text_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage = ProviderUsage()
        metadata = ProviderMetadata(model=self.model)

        try:
            async for chunk in response:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage = ProviderUsage(
                        input_tokens=int(getattr(chunk_usage, "prompt_tokens", 0) or 0),
                        output_tokens=int(getattr(chunk_usage, "completion_tokens", 0) or 0),
                        cache_read_tokens=int(
                            getattr(getattr(chunk_usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
                        ),
                    )
                if getattr(chunk, "id", None):
                    metadata.request_id = str(chunk.id)
                if getattr(chunk, "model", None):
                    metadata.model = str(chunk.model)
                if not chunk.choices:
                    continue
                finish = getattr(chunk.choices[0], "finish_reason", None)
                if finish:
                    metadata.finish_reason = str(finish)

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
            raise ProviderError.from_exception(e) from e

        content: list[TextBlock | ToolUseBlock] = []
        full_text = "".join(text_parts)
        if full_text:
            content.append(TextBlock(text=full_text))

        structured_ids: set[str] = set()
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
            structured_ids.add(tc_data["id"])
            yield StreamEvent(
                type="tool_use_end",
                tool_name=tc_data["name"],
                tool_id=tc_data["id"],
                tool_input=args,
            )

        content = apply_text_tool_recovery(content, tools)
        for block in content:
            if isinstance(block, ToolUseBlock) and block.id not in structured_ids:
                yield StreamEvent(
                    type="tool_use_start",
                    tool_name=block.name,
                    tool_id=block.id,
                )
                yield StreamEvent(
                    type="tool_use_end",
                    tool_name=block.name,
                    tool_id=block.id,
                    tool_input=block.input,
                )

        yield StreamEvent(
            type="done",
            response=ProviderResponse(
                thinking=None,
                content=content,
                usage=usage,
                metadata=metadata,
            ),
        )
