"""Google Gemini provider — supports Gemini 2.0, 1.5, etc."""

from __future__ import annotations

import json
import uuid

from .base import (
    Provider,
    ProviderError,
    ProviderResponse,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


def _anthropic_tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schemas to Gemini function declarations."""
    declarations = []
    for tool in tools:
        schema = tool.get("input_schema", {"type": "object", "properties": {}})
        # Gemini doesn't support 'default' in parameter schemas — strip them
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

        # Map roles: Anthropic user/assistant → Gemini user/model
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
                    # Skip thinking blocks

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

    async def send(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Send messages to Gemini API and return normalized response."""
        try:
            from google.genai import types

            # Build config
            config: dict = {
                "system_instruction": system_prompt,
                "max_output_tokens": self.max_tokens,
            }

            # Add tools if present
            if tools:
                declarations = _anthropic_tools_to_gemini(tools)
                config["tools"] = [types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(**d) for d in declarations
                    ]
                )]

            # Convert messages
            contents = _convert_messages(messages)

            # Call the API (synchronous — run in thread)
            import asyncio
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )

        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(str(e)) from e

        # Parse response
        content: list[TextBlock | ToolUseBlock] = []
        thinking: ThinkingBlock | None = None

        if response.candidates:
            candidate = response.candidates[0]
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    content.append(TextBlock(text=part.text))
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    # Convert args to dict
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

        # Fallback: if response has text attribute directly
        if not content and hasattr(response, "text") and response.text:
            content.append(TextBlock(text=response.text))

        return ProviderResponse(thinking=thinking, content=content)
