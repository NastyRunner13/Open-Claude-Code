"""Google Gemini provider — supports Gemini 2.0, 1.5, etc."""

from __future__ import annotations

import asyncio
import json
import uuid

from collections.abc import AsyncIterator

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


def _anthropic_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schemas to Gemini function declarations."""
    declarations = []
    for tool in tools:
        schema = tool.get("input_schema", {"type": "object", "properties": {}})
        cleaned = _strip_defaults(schema)
        declarations.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": cleaned,
        })
    return declarations


def _strip_defaults(schema: dict) -> dict:
    """Recursively strip 'default' keys from JSON schema (Gemini doesn't support them)."""
    result = {}
    for k, v in schema.items():
        if k == "default":
            continue
        if isinstance(v, dict):
            result[k] = _strip_defaults(v)
        elif isinstance(v, list):
            result[k] = [_strip_defaults(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _convert_messages(messages: list[dict]) -> list[dict]:
    """Convert Anthropic-style messages to Gemini content format."""
    contents = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        gemini_role = "model" if role == "assistant" else "user"

        if isinstance(content, str):
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}],
            })
            continue

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                    if btype == "text":
                        parts.append({"text": block["text"]})
                    elif btype == "tool_use":
                        parts.append({
                            "functionCall": {
                                "name": block["name"],
                                "args": block["input"],
                            }
                        })
                    elif btype == "tool_result":
                        parts.append({
                            "functionResponse": {
                                "name": block.get("tool_use_id", "unknown"),
                                "response": {"result": block.get("content", "")},
                            }
                        })

            if parts:
                contents.append({"role": gemini_role, "parts": parts})

    return contents


class GeminiProvider(Provider):
    """Google Gemini provider using the google-genai SDK."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        max_tokens: int = 16000,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._api_key = api_key

        try:
            from google import genai
            self._genai = genai
            self.client = genai.Client(api_key=api_key)
        except ImportError:
            raise ProviderError(
                "Google GenAI SDK not installed. Run: uv add google-genai"
            )

    @property
    def model_name(self) -> str:
        return self.model

    def _build_config_and_contents(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> tuple:
        """Build config and contents shared by send() and stream()."""
        from google.genai import types

        config: dict = {
            "system_instruction": system_prompt,
            "max_output_tokens": self.max_tokens,
        }

        if tools:
            declarations = _anthropic_tools_to_gemini(tools)
            config["tools"] = [types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(**d) for d in declarations
                ]
            )]

        contents = _convert_messages(messages)
        return types.GenerateContentConfig(**config), contents

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to Gemini API and return normalized response."""
        try:
            config, contents = self._build_config_and_contents(
                messages, tools, system_prompt
            )

            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=config,
            )

        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(str(e)) from e

        content: list[TextBlock | ToolUseBlock] = []
        thinking: ThinkingBlock | None = None

        if response.candidates:
            candidate = response.candidates[0]
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    content.append(TextBlock(text=part.text))
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args = dict(fc.args) if fc.args else {}
                    content.append(ToolUseBlock(
                        id=f"gemini_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        input=args,
                    ))
                elif hasattr(part, "thought") and part.thought:
                    thinking = ThinkingBlock(
                        thinking=part.text if hasattr(part, "text") else str(part.thought),
                        signature="",
                    )

        if not content and hasattr(response, "text") and response.text:
            content.append(TextBlock(text=response.text))

        return ProviderResponse(thinking=thinking, content=content)

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[StreamEvent]:
        """Stream response tokens from Gemini using generate_content_stream."""
        try:
            config, contents = self._build_config_and_contents(
                messages, tools, system_prompt
            )
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(str(e)) from e

        text_parts: list[str] = []
        tool_blocks: list[ToolUseBlock] = []

        try:
            # Gemini's streaming is synchronous — run in thread with queue
            import queue

            q: queue.Queue = queue.Queue()

            def _stream_in_thread() -> None:
                try:
                    for chunk in self.client.models.generate_content_stream(
                        model=self.model,
                        contents=contents,
                        config=config,
                    ):
                        q.put(("chunk", chunk))
                    q.put(("done", None))
                except Exception as e:
                    q.put(("error", e))

            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, _stream_in_thread)

            while True:
                # Poll the queue with async sleep to avoid blocking
                try:
                    msg_type, data = await asyncio.to_thread(q.get, timeout=30)
                except Exception:
                    break

                if msg_type == "error":
                    raise ProviderError(str(data)) from data
                if msg_type == "done":
                    break

                chunk = data
                if chunk.candidates:
                    candidate = chunk.candidates[0]
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                text_parts.append(part.text)
                                yield StreamEvent(type="text_delta", text=part.text)
                            elif hasattr(part, "function_call") and part.function_call:
                                fc = part.function_call
                                args = dict(fc.args) if fc.args else {}
                                tool_id = f"gemini_{uuid.uuid4().hex[:8]}"
                                tool_blocks.append(ToolUseBlock(
                                    id=tool_id,
                                    name=fc.name,
                                    input=args,
                                ))
                                yield StreamEvent(
                                    type="tool_use_start",
                                    tool_name=fc.name,
                                    tool_id=tool_id,
                                )
                                yield StreamEvent(
                                    type="tool_use_end",
                                    tool_name=fc.name,
                                    tool_id=tool_id,
                                    tool_input=args,
                                )

        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(str(e)) from e

        # Build final response
        content: list[TextBlock | ToolUseBlock] = []
        full_text = "".join(text_parts)
        if full_text:
            content.append(TextBlock(text=full_text))
        content.extend(tool_blocks)

        yield StreamEvent(
            type="done",
            response=ProviderResponse(thinking=None, content=content),
        )
