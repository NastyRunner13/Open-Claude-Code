"""Ollama provider — local models via the native chat API.

Ollama's OpenAI-compat shim at `/v1` silently truncates same-session history.
This provider POSTs `/api/chat` and always sends `num_ctx` (default 32768).
LM Studio / vLLM still use OpenAIProvider via `--base-url`.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

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

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_NUM_CTX = 32768


def normalize_ollama_url(url: str | None = None) -> str:
    """Return the native Ollama origin. Strips a leftover `/v1` from old configs."""
    if url is None or not str(url).strip():
        raw = (os.environ.get("OLLAMA_HOST") or DEFAULT_BASE_URL).strip()
    else:
        raw = str(url).strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw


def resolve_num_ctx(explicit: int | None = None) -> int:
    """Pick num_ctx: constructor/YAML, then OCC_OLLAMA_NUM_CTX, then 32768."""
    if explicit is not None:
        try:
            return max(1, int(explicit))
        except (TypeError, ValueError):
            return DEFAULT_NUM_CTX
    env = os.environ.get("OCC_OLLAMA_NUM_CTX", "").strip()
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return DEFAULT_NUM_CTX


def convert_messages(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-style history to Ollama's native chat messages."""
    converted: list[dict] = []
    id_to_name: dict[str, str] = {}
    for msg in messages:
        role = msg.get("role") or "user"
        content = msg.get("content")
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            continue

        if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                tool_id = str(block.get("tool_use_id") or "")
                name = str(block.get("name") or id_to_name.get(tool_id, ""))
                item: dict = {"role": "tool", "content": str(block.get("content") or "")}
                if name:
                    item["tool_name"] = name
                converted.append(item)
            continue

        if role == "assistant":
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif kind == "thinking":
                    thinking_parts.append(str(block.get("thinking") or ""))
                elif kind == "tool_use":
                    call_id = str(block.get("id") or "")
                    name = str(block.get("name") or "")
                    if call_id and name:
                        id_to_name[call_id] = name
                    raw_input = block.get("input")
                    tool_calls.append({
                        "function": {
                            "name": name,
                            "arguments": raw_input if isinstance(raw_input, dict) else {},
                        }
                    })
            item = {"role": "assistant", "content": "\n".join(text_parts)}
            if thinking_parts:
                item["thinking"] = "\n".join(thinking_parts)
            if tool_calls:
                item["tool_calls"] = tool_calls
            converted.append(item)
            continue

        text_parts = [
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if text_parts:
            converted.append({"role": role, "content": "\n".join(text_parts)})
    return converted


def _tools_payload(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def _parse_arguments(raw: object) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"raw": raw}
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    return {}


def _tool_call_id(tool_call: dict, index: int) -> str:
    if tool_call.get("id"):
        return str(tool_call["id"])
    function = tool_call.get("function") or {}
    if function.get("id"):
        return str(function["id"])
    return f"ollama_tool_{index}"


def _usage_from(payload: dict) -> tuple[ProviderUsage, ProviderMetadata]:
    duration = payload.get("total_duration")
    latency_ms = 0.0
    if isinstance(duration, (int, float)):
        latency_ms = duration / 1_000_000
    usage = ProviderUsage(
        input_tokens=int(payload.get("prompt_eval_count") or 0),
        output_tokens=int(payload.get("eval_count") or 0),
        cache_read_tokens=int(payload.get("prompt_eval_cached_count") or 0),
    )
    metadata = ProviderMetadata(
        finish_reason=str(payload.get("done_reason") or ""),
        latency_ms=latency_ms,
        model=str(payload.get("model") or ""),
    )
    return usage, metadata


def _blocks_from_message(
    message: dict,
    tools: list[dict],
) -> tuple[list[TextBlock | ToolUseBlock], ThinkingBlock | None]:
    content: list[TextBlock | ToolUseBlock] = []
    thinking_text = message.get("thinking") or ""
    thinking = ThinkingBlock(thinking=thinking_text, signature="") if thinking_text else None
    text = message.get("content") or ""
    if text:
        content.append(TextBlock(text=text))
    for index, tool_call in enumerate(message.get("tool_calls") or []):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function") or {}
        content.append(ToolUseBlock(
            id=_tool_call_id(tool_call, index),
            name=str(function.get("name") or ""),
            input=_parse_arguments(function.get("arguments")),
        ))
    return apply_text_tool_recovery(content, tools), thinking


class OllamaProvider(Provider):
    """Local Ollama models over POST /api/chat."""

    def __init__(
        self,
        model: str = "llama3.2",
        max_tokens: int = 16000,
        base_url: str | None = None,
        num_ctx: int | None = None,
    ) -> None:
        if model.startswith("ollama/"):
            model = model[7:]
        self.model = model
        self.max_tokens = max_tokens
        self.base_url = normalize_ollama_url(base_url)
        self.num_ctx = resolve_num_ctx(num_ctx)
        self._client: httpx.AsyncClient | None = None

    @property
    def model_name(self) -> str:
        return f"ollama/{self.model}"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(None, connect=10.0),
            )
        return self._client

    def _chat_url(self) -> str:
        return f"{self.base_url}/api/chat"

    def _payload(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
        *,
        stream: bool,
    ) -> dict:
        chat_messages: list[dict] = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(convert_messages(messages))
        payload: dict = {
            "model": self.model,
            "messages": chat_messages,
            "stream": stream,
            "options": {
                "num_ctx": self.num_ctx,
                "num_predict": self.max_tokens,
            },
        }
        if tools:
            payload["tools"] = _tools_payload(tools)
        return payload

    def _error_from_body(self, body: str, status_code: int | None) -> ProviderError:
        text = body.strip() or f"Ollama HTTP {status_code}"
        try:
            data = json.loads(body)
            if isinstance(data, dict) and data.get("error"):
                text = str(data["error"])
        except json.JSONDecodeError:
            pass
        lowered = text.lower()
        if status_code == 404 and "not found" in lowered:
            text = (
                f"Ollama model not found ({self.model}). "
                f"Pull it with: ollama pull {self.model}"
            )
        transient = isinstance(status_code, int) and status_code >= 500
        return ProviderError(text, transient=transient, status_code=status_code)

    def _wrap_transport(self, error: Exception) -> ProviderError:
        if isinstance(error, httpx.ConnectError):
            return ProviderError(
                f"Cannot reach Ollama at {self.base_url}. Is `ollama serve` running?",
                transient=False,
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderError(str(error), transient=True)
        return ProviderError.from_exception(error)

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        payload = self._payload(messages, tools, system_prompt, stream=False)
        try:
            response = await self._http().post(self._chat_url(), json=payload)
        except httpx.RequestError as error:
            raise self._wrap_transport(error) from error
        if response.status_code >= 400:
            raise self._error_from_body(response.text, response.status_code)
        try:
            data = response.json()
        except json.JSONDecodeError as error:
            raise ProviderError("Ollama returned invalid JSON") from error
        if isinstance(data, dict) and data.get("error"):
            raise ProviderError(str(data["error"]), status_code=response.status_code)
        message = (data or {}).get("message") or {}
        content, thinking = _blocks_from_message(message, tools)
        usage, metadata = _usage_from(data if isinstance(data, dict) else {})
        if not metadata.model:
            metadata.model = self.model
        return ProviderResponse(
            thinking=thinking,
            content=content,
            usage=usage,
            metadata=metadata,
        )

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._payload(messages, tools, system_prompt, stream=True)
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage = ProviderUsage()
        metadata = ProviderMetadata(model=self.model)
        started_ids: set[str] = set()

        try:
            async with self._http().stream("POST", self._chat_url(), json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise self._error_from_body(body, response.status_code)
                async for line in response.aiter_lines():
                    if not line or not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ProviderError("Ollama stream returned invalid JSON") from error
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise ProviderError(str(chunk["error"]))
                    if chunk.get("model"):
                        metadata.model = str(chunk["model"])
                    if chunk.get("done"):
                        chunk_usage, chunk_meta = _usage_from(chunk)
                        usage = chunk_usage
                        metadata.finish_reason = chunk_meta.finish_reason
                        metadata.latency_ms = chunk_meta.latency_ms

                    message = chunk.get("message") or {}
                    delta_think = message.get("thinking") or ""
                    if delta_think:
                        thinking_parts.append(delta_think)
                        yield StreamEvent(type="thinking_delta", text=delta_think)
                    delta_text = message.get("content") or ""
                    if delta_text:
                        text_parts.append(delta_text)
                        yield StreamEvent(type="text_delta", text=delta_text)
                    for index, tool_call in enumerate(message.get("tool_calls") or []):
                        if not isinstance(tool_call, dict):
                            continue
                        function = tool_call.get("function") or {}
                        if index not in tool_calls_acc:
                            tool_calls_acc[index] = {
                                "id": _tool_call_id(tool_call, index),
                                "name": str(function.get("name") or ""),
                                "arguments": {},
                            }
                        entry = tool_calls_acc[index]
                        if function.get("name"):
                            entry["name"] = str(function["name"])
                        if tool_call.get("id"):
                            entry["id"] = str(tool_call["id"])
                        parsed = _parse_arguments(function.get("arguments"))
                        if parsed:
                            entry["arguments"].update(parsed)
                        if entry["name"] and entry["id"] not in started_ids:
                            started_ids.add(entry["id"])
                            yield StreamEvent(
                                type="tool_use_start",
                                tool_name=entry["name"],
                                tool_id=entry["id"],
                            )
        except ProviderError:
            raise
        except httpx.RequestError as error:
            raise self._wrap_transport(error) from error

        content: list[TextBlock | ToolUseBlock] = []
        full_text = "".join(text_parts)
        if full_text:
            content.append(TextBlock(text=full_text))
        structured_ids: set[str] = set()
        for entry in tool_calls_acc.values():
            content.append(ToolUseBlock(
                id=entry["id"],
                name=entry["name"],
                input=entry["arguments"],
            ))
            structured_ids.add(entry["id"])
            yield StreamEvent(
                type="tool_use_end",
                tool_name=entry["name"],
                tool_id=entry["id"],
                tool_input=entry["arguments"],
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

        thinking = None
        full_thinking = "".join(thinking_parts)
        if full_thinking:
            thinking = ThinkingBlock(thinking=full_thinking, signature="")

        yield StreamEvent(
            type="done",
            response=ProviderResponse(
                thinking=thinking,
                content=content,
                usage=usage,
                metadata=metadata,
            ),
        )
