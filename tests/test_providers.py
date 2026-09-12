"""Tests for the provider registry and message conversion utilities."""

import os

import pytest

from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock
from open_claude_code.providers.registry import create_provider, resolve_provider


class TestRegistryAutoDetection:
    """Test that the registry maps model names to correct providers."""

    def test_claude_model(self):
        p = create_provider("claude-sonnet-4-20250514")
        from open_claude_code.providers.anthropic import AnthropicProvider
        assert isinstance(p, AnthropicProvider)

    def test_gpt_model(self):
        p = create_provider("gpt-4o", api_key="test-key")
        from open_claude_code.providers.openai import OpenAIProvider
        assert isinstance(p, OpenAIProvider)

    def test_o1_model(self):
        p = create_provider("o1-preview", api_key="test-key")
        from open_claude_code.providers.openai import OpenAIProvider
        assert isinstance(p, OpenAIProvider)

    def test_o3_model(self):
        p = create_provider("o3-mini", api_key="test-key")
        from open_claude_code.providers.openai import OpenAIProvider
        assert isinstance(p, OpenAIProvider)

    def test_gemini_model(self):
        try:
            import google.genai  # noqa: F401
        except ImportError:
            pytest.skip("google-genai not installed (optional dependency)")
        p = create_provider("gemini-2.0-flash", api_key="test-key")
        from open_claude_code.providers.gemini import GeminiProvider
        assert isinstance(p, GeminiProvider)

    def test_groq_prefix(self):
        p = create_provider("groq/llama-3.3-70b-versatile", api_key="test-key")
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, GroqProvider)

    def test_ollama_prefix(self):
        p = create_provider("ollama/llama3.2")
        from open_claude_code.providers.ollama import OllamaProvider
        assert isinstance(p, OllamaProvider)

    def test_custom_base_url(self):
        p = create_provider(
            "my-custom-model",
            api_key="test-key",
            base_url="https://my-endpoint.com/v1",
        )
        from open_claude_code.providers.openai import OpenAIProvider
        assert isinstance(p, OpenAIProvider)

    def test_unknown_defaults_to_anthropic(self):
        p = create_provider("some-unknown-model")
        from open_claude_code.providers.anthropic import AnthropicProvider
        assert isinstance(p, AnthropicProvider)

    def test_groq_prefix_with_nested_vendor_id(self):
        p = create_provider("groq/openai/gpt-oss-120b", api_key="test-key")
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, GroqProvider)
        assert p.model == "openai/gpt-oss-120b"

    def test_unprefixed_llama_is_not_groq_even_with_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        p = create_provider("llama-3.3-70b-versatile")
        from open_claude_code.providers.anthropic import AnthropicProvider
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, AnthropicProvider)
        assert not isinstance(p, GroqProvider)

    def test_unprefixed_deepseek_is_not_groq_even_with_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        p = create_provider("deepseek-chat")
        from open_claude_code.providers.anthropic import AnthropicProvider
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, AnthropicProvider)
        assert not isinstance(p, GroqProvider)

    def test_openrouter_prefix(self):
        p = create_provider("openrouter/anthropic/claude-sonnet-4", api_key="test-key")
        from open_claude_code.providers.openrouter import OpenRouterProvider
        assert isinstance(p, OpenRouterProvider)
        assert p.model == "anthropic/claude-sonnet-4"

    def test_openrouter_native_id(self):
        p = create_provider("openrouter/auto", api_key="test-key")
        from open_claude_code.providers.openrouter import OpenRouterProvider
        assert isinstance(p, OpenRouterProvider)
        assert p.model == "auto"

    def test_openrouter_vendor_model_with_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        p = create_provider("anthropic/claude-sonnet-4")
        from open_claude_code.providers.openrouter import OpenRouterProvider
        assert isinstance(p, OpenRouterProvider)
        assert p.model == "anthropic/claude-sonnet-4"

    def test_openrouter_heuristic_skips_groq_prefix(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        p = create_provider("groq/llama-3.3-70b-versatile", api_key="test-key")
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, GroqProvider)

    def test_openrouter_heuristic_skips_ollama_prefix(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        p = create_provider("ollama/llama3.2")
        from open_claude_code.providers.ollama import OllamaProvider
        assert isinstance(p, OllamaProvider)

    def test_openrouter_heuristic_off_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        p = create_provider("anthropic/claude-sonnet-4")
        from open_claude_code.providers.anthropic import AnthropicProvider
        assert isinstance(p, AnthropicProvider)

    def test_base_url_wins_over_openrouter_heuristic(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        p = create_provider(
            "org/custom-model",
            api_key="test-key",
            base_url="https://my-vllm.example/v1",
        )
        from open_claude_code.providers.openai import OpenAIProvider
        assert isinstance(p, OpenAIProvider)

    def test_openrouter_missing_key(self, monkeypatch):
        from open_claude_code.providers.base import ProviderError

        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
            create_provider("openrouter/anthropic/claude-sonnet-4")

    def test_resolve_provider_matches_create_without_instantiation(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert resolve_provider("openrouter/anthropic/claude-sonnet-4") == "openrouter"
        assert resolve_provider("groq/llama-3.3-70b-versatile") == "groq"
        assert resolve_provider("ollama/llama3.2") == "ollama"
        assert resolve_provider("gpt-4o") == "openai"
        assert resolve_provider("claude-sonnet-4") == "anthropic"
        assert resolve_provider("llama-3.3-70b-versatile") == "anthropic"
        assert resolve_provider("custom", base_url="http://localhost:8000/v1") == "openai-compat"


class TestProviderModelName:
    """Test model_name property for each provider."""

    def test_anthropic_model_name(self):
        p = create_provider("claude-sonnet-4-20250514")
        assert p.model_name == "claude-sonnet-4-20250514"

    def test_openai_model_name(self):
        p = create_provider("gpt-4o", api_key="test")
        assert p.model_name == "gpt-4o"

    def test_groq_model_name(self):
        p = create_provider("groq/llama-3.3-70b-versatile", api_key="test")
        assert p.model_name == "groq/llama-3.3-70b-versatile"

    def test_ollama_model_name(self):
        p = create_provider("ollama/llama3.2")
        assert p.model_name == "ollama/llama3.2"

    def test_openrouter_model_name_strips_prefix(self):
        p = create_provider("openrouter/openai/gpt-4o", api_key="test")
        assert p.model_name == "openrouter/openai/gpt-4o"


class TestOpenRouterDefaults:
    def test_header_defaults_and_base_url(self):
        from open_claude_code.providers.openrouter import (
            DEFAULT_BASE_URL,
            DEFAULT_HEADERS,
            OpenRouterProvider,
        )

        p = OpenRouterProvider(model="openrouter/openai/gpt-4o", api_key="test")
        headers = p._inner.client.default_headers
        assert headers["HTTP-Referer"] == DEFAULT_HEADERS["HTTP-Referer"]
        assert headers["X-Title"] == DEFAULT_HEADERS["X-Title"]
        assert str(p._inner.client.base_url).rstrip("/") == DEFAULT_BASE_URL.rstrip("/")
        assert p.default_headers == DEFAULT_HEADERS


class TestOpenAIMessageConversion:
    """Test Anthropic → OpenAI message format conversion."""

    def test_simple_text_messages(self):
        from open_claude_code.providers.openai import _convert_messages
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = _convert_messages(msgs)
        assert result == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    def test_tool_result_converts_to_tool_role(self):
        from open_claude_code.providers.openai import _convert_messages
        msgs = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "file contents"},
            ]},
        ]
        result = _convert_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "t1"

    def test_tool_use_converts_to_tool_calls(self):
        from open_claude_code.providers.openai import _convert_messages
        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"file_path": "test.py"}},
            ]},
        ]
        result = _convert_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"

    def test_thinking_blocks_stripped(self):
        from open_claude_code.providers.openai import _convert_messages
        msgs = [
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hmm...", "signature": "sig1"},
                {"type": "text", "text": "the answer is 42"},
            ]},
        ]
        result = _convert_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "the answer is 42"
        # No tool_calls key
        assert "tool_calls" not in result[0]


class TestToolSchemaConversion:
    """Test Anthropic → OpenAI tool schema conversion."""

    def test_basic_conversion(self):
        from open_claude_code.providers.openai import _anthropic_tools_to_openai
        tools = [{
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }]
        result = _anthropic_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["function"]["parameters"]["properties"]["path"]["type"] == "string"


class TestGeminiFunctionResponseName:
    """Gemini needs the declaration name, not the tool_use_id."""

    def test_function_response_uses_declaration_name(self):
        from open_claude_code.providers.gemini import _convert_messages

        msgs = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "gemini_abc123", "name": "read_file", "input": {"file_path": "a.py"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "gemini_abc123", "content": "print(1)"},
            ]},
        ]
        result = _convert_messages(msgs)
        response = result[1]["parts"][0]["functionResponse"]
        assert response["name"] == "read_file"
        assert response["response"]["result"] == "print(1)"


class TestAnthropicThinkingOptIn:
    def test_thinking_enabled_for_sonnet_4(self):
        from open_claude_code.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(model="claude-sonnet-4-20250514")
        kwargs = provider._build_kwargs([], [], "system")
        assert kwargs["thinking"]["type"] == "enabled"

    def test_thinking_not_forced_on_haiku(self):
        from open_claude_code.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider(model="claude-3-haiku-20240307")
        kwargs = provider._build_kwargs([], [], "system")
        assert "thinking" not in kwargs


def _api_error(message: str, status_code: int = 400) -> Exception:
    error = Exception(message)
    error.status_code = status_code  # type: ignore[attr-defined]
    return error


def _completion(text: str = "ok"):
    from unittest.mock import MagicMock

    usage = MagicMock()
    usage.prompt_tokens = 4
    usage.completion_tokens = 2
    usage.prompt_tokens_details = None
    message = MagicMock()
    message.content = text
    message.tool_calls = None
    message.reasoning_content = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.id = "req-1"
    response.model = "gpt-4o"
    return response


def _delta_chunk(text: str | None = None, *, usage=None, finish: str | None = None):
    from unittest.mock import MagicMock

    chunk = MagicMock()
    chunk.id = "req-1"
    chunk.model = "gpt-4o"
    chunk.usage = usage
    if text is None and usage is not None:
        chunk.choices = []
        return chunk
    delta = MagicMock()
    delta.content = text
    delta.tool_calls = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish
    chunk.choices = [choice]
    return chunk


class _FakeStream:
    def __init__(self, chunks: list) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _bind_create(provider, create):
    provider.client.chat.completions.create = create
    return provider


class TestOpenAICompatFallback:
    """max_tokens / include_usage fallback and tool-rejection errors. No live API."""

    def test_send_uses_max_completion_tokens(self):
        import asyncio

        from open_claude_code.providers.openai import OpenAIProvider

        calls: list[dict] = []

        async def create(**kwargs):
            calls.append(kwargs)
            return _completion("hello")

        provider = _bind_create(OpenAIProvider(model="gpt-4o", api_key="test", max_tokens=128), create)
        result = asyncio.run(provider.send([], [], "sys"))
        assert result.content[0].text == "hello"
        assert calls[0]["max_completion_tokens"] == 128
        assert "max_tokens" not in calls[0]
        assert "stream" not in calls[0]

    def test_send_retries_with_max_tokens_on_400_and_remembers(self):
        import asyncio

        from open_claude_code.providers.openai import OpenAIProvider

        calls: list[dict] = []

        async def create(**kwargs):
            calls.append(kwargs)
            if "max_completion_tokens" in kwargs:
                raise _api_error("Unknown parameter: 'max_completion_tokens'")
            return _completion("ok")

        provider = _bind_create(OpenAIProvider(model="local-model", api_key="test", max_tokens=64), create)
        first = asyncio.run(provider.send([], [], "sys"))
        assert first.content[0].text == "ok"
        assert "max_completion_tokens" in calls[0]
        assert calls[1]["max_tokens"] == 64
        assert "max_completion_tokens" not in calls[1]

        asyncio.run(provider.send([], [], "sys"))
        assert calls[2]["max_tokens"] == 64
        assert "max_completion_tokens" not in calls[2]

    def test_stream_requests_include_usage(self):
        import asyncio

        from open_claude_code.providers.openai import OpenAIProvider

        calls: list[dict] = []
        usage = type("U", (), {"prompt_tokens": 7, "completion_tokens": 3, "prompt_tokens_details": None})()

        async def create(**kwargs):
            calls.append(kwargs)
            return _FakeStream([
                _delta_chunk("hi", finish="stop"),
                _delta_chunk(usage=usage),
            ])

        provider = _bind_create(OpenAIProvider(model="gpt-4o", api_key="test"), create)

        async def drain():
            events = []
            async for event in provider.stream([], [], "sys"):
                events.append(event)
            return events

        events = asyncio.run(drain())
        assert calls[0]["stream"] is True
        assert calls[0]["stream_options"] == {"include_usage": True}
        done = events[-1]
        assert done.type == "done"
        assert done.response is not None
        assert done.response.usage.input_tokens == 7
        assert done.response.usage.output_tokens == 3

    def test_stream_drops_include_usage_after_400(self):
        import asyncio

        from open_claude_code.providers.openai import OpenAIProvider

        calls: list[dict] = []

        async def create(**kwargs):
            calls.append(kwargs)
            if "stream_options" in kwargs:
                raise _api_error("Unknown parameter: 'stream_options'")
            return _FakeStream([_delta_chunk("ok", finish="stop")])

        provider = _bind_create(OpenAIProvider(model="ollama-local", api_key="test"), create)

        async def drain():
            events = []
            async for event in provider.stream([], [], "sys"):
                events.append(event)
            return events

        events = asyncio.run(drain())
        assert "stream_options" in calls[0]
        assert "stream_options" not in calls[1]
        assert events[-1].type == "done"

        asyncio.run(drain())
        assert "stream_options" not in calls[2]

    def test_tool_rejection_is_a_clear_provider_error(self):
        import asyncio

        import pytest

        from open_claude_code.providers.base import ProviderError
        from open_claude_code.providers.openai import OpenAIProvider

        async def create(**kwargs):
            raise _api_error("tool use is not supported with this model")

        provider = _bind_create(OpenAIProvider(model="whisper-large-v3", api_key="test"), create)
        tools = [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
        with pytest.raises(ProviderError, match="does not support tool calling") as exc:
            asyncio.run(provider.send([], tools, "sys"))
        assert exc.value.status_code == 400
        assert not exc.value.transient

    def test_stream_429_is_transient(self):
        import asyncio

        import pytest

        from open_claude_code.providers.base import ProviderError
        from open_claude_code.providers.openai import OpenAIProvider

        async def create(**kwargs):
            raise _api_error("rate limited", status_code=429)

        provider = _bind_create(OpenAIProvider(model="gpt-4o", api_key="test"), create)

        async def drain():
            async for _ in provider.stream([], [], "sys"):
                pass

        with pytest.raises(ProviderError) as exc:
            asyncio.run(drain())
        assert exc.value.transient
        assert exc.value.status_code == 429


class _FakeOllamaResponse:
    def __init__(self, *, status_code=200, json_body=None, lines=None, text=""):
        import json as _json
        self.status_code = status_code
        self._json = json_body
        self._lines = lines or []
        if text:
            self.text = text
        elif json_body is not None:
            self.text = _json.dumps(json_body)
        else:
            self.text = "\n".join(self._lines)

    def json(self):
        import json as _json
        if self._json is None:
            raise _json.JSONDecodeError("no json", self.text, 0)
        return self._json

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeOllamaClient:
    def __init__(self, responses: list):
        self.requests: list[dict] = []
        self._responses = list(responses)
        self.is_closed = False

    def _next(self, url, json_body, stream):
        self.requests.append({"url": url, "json": json_body, "stream": stream})
        if not self._responses:
            raise AssertionError("no fake Ollama responses left")
        return self._responses.pop(0)

    async def post(self, url, json=None):
        return self._next(url, json, False)

    def stream(self, method, url, json=None):
        return self._next(url, json, True)


def _bind_ollama(provider, responses):
    client = _FakeOllamaClient(responses)
    provider._client = client
    return provider, client


class TestOllamaNative:
    def test_strips_v1_and_sends_num_ctx(self):
        from open_claude_code.providers.ollama import DEFAULT_NUM_CTX, OllamaProvider

        p = OllamaProvider(model="ollama/llama3.2", base_url="http://localhost:11434/v1")
        assert p.base_url == "http://localhost:11434"
        assert p.num_ctx == DEFAULT_NUM_CTX
        assert p.model == "llama3.2"
        payload = p._payload([], [], "sys", stream=True)
        assert payload["model"] == "llama3.2"
        assert payload["options"]["num_ctx"] == DEFAULT_NUM_CTX
        assert payload["options"]["num_predict"] == 16000
        assert payload["stream"] is True
        assert payload["messages"][0] == {"role": "system", "content": "sys"}

    def test_num_ctx_from_env(self, monkeypatch):
        from open_claude_code.providers.ollama import OllamaProvider

        monkeypatch.setenv("OCC_OLLAMA_NUM_CTX", "8192")
        p = OllamaProvider(model="llama3.2")
        assert p.num_ctx == 8192

    def test_explicit_num_ctx_wins_over_env(self, monkeypatch):
        from open_claude_code.providers.ollama import OllamaProvider

        monkeypatch.setenv("OCC_OLLAMA_NUM_CTX", "8192")
        p = OllamaProvider(model="llama3.2", num_ctx=4096)
        assert p.num_ctx == 4096

    def test_ollama_host_env(self, monkeypatch):
        from open_claude_code.providers.ollama import OllamaProvider, normalize_ollama_url

        monkeypatch.setenv("OLLAMA_HOST", "192.168.1.9:11434")
        assert normalize_ollama_url(None) == "http://192.168.1.9:11434"
        p = OllamaProvider(model="llama3.2")
        assert p.base_url == "http://192.168.1.9:11434"

    def test_create_provider_passes_num_ctx(self):
        from open_claude_code.providers.ollama import OllamaProvider

        p = create_provider("ollama/qwen2.5-coder", num_ctx=16384)
        assert isinstance(p, OllamaProvider)
        assert p.num_ctx == 16384
        assert p.model_name == "ollama/qwen2.5-coder"

    def test_convert_tool_history_uses_native_shape(self):
        from open_claude_code.providers.ollama import convert_messages

        history = [
            {"role": "user", "content": "read it"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "I should read", "signature": ""},
                {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"file_path": "a.py"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "print(1)"},
            ]},
        ]
        out = convert_messages(history)
        assert out[0] == {"role": "user", "content": "read it"}
        assert out[1]["role"] == "assistant"
        assert out[1]["thinking"] == "I should read"
        assert out[1]["tool_calls"][0]["function"] == {
            "name": "read_file",
            "arguments": {"file_path": "a.py"},
        }
        assert out[2] == {"role": "tool", "content": "print(1)", "tool_name": "read_file"}

    def test_send_maps_usage_and_native_tool_calls(self):
        import asyncio

        from open_claude_code.providers.base import ToolUseBlock
        from open_claude_code.providers.ollama import OllamaProvider

        tools = [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
        body = {
            "model": "llama3.2",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "echo",
                        "arguments": {"message": "hi"},
                    }
                }],
            },
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 11,
            "eval_count": 4,
            "prompt_eval_cached_count": 2,
            "total_duration": 2_000_000_000,
        }
        provider, client = _bind_ollama(OllamaProvider(model="ollama/llama3.2"), [
            _FakeOllamaResponse(json_body=body),
        ])
        result = asyncio.run(provider.send([{"role": "user", "content": "hi"}], tools, "sys"))
        assert client.requests[0]["url"].endswith("/api/chat")
        assert "/v1" not in client.requests[0]["url"]
        assert client.requests[0]["json"]["options"]["num_ctx"] == 32768
        assert client.requests[0]["json"]["stream"] is False
        blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert blocks[0].name == "echo"
        assert blocks[0].input == {"message": "hi"}
        assert blocks[0].id == "ollama_tool_0"
        assert result.usage.input_tokens == 11
        assert result.usage.output_tokens == 4
        assert result.usage.cache_read_tokens == 2
        assert result.metadata.latency_ms == 2000.0

    def test_send_recovers_xml_tool_calls(self):
        import asyncio

        from open_claude_code.providers.base import ToolUseBlock
        from open_claude_code.providers.ollama import OllamaProvider

        tools = [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
        xml = '<tool_call>{"name": "echo", "arguments": {"message": "ping"}}</tool_call>'
        provider, _client = _bind_ollama(OllamaProvider(model="qwen2.5"), [
            _FakeOllamaResponse(json_body={
                "message": {"role": "assistant", "content": xml},
                "done": True,
            }),
        ])
        result = asyncio.run(provider.send([], tools, "sys"))
        blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert blocks[0].name == "echo"
        assert blocks[0].input == {"message": "ping"}

    def test_stream_text_thinking_usage(self):
        import asyncio
        import json

        from open_claude_code.providers.ollama import OllamaProvider

        lines = [
            json.dumps({"message": {"role": "assistant", "thinking": "hmm "}, "done": False}),
            json.dumps({"message": {"role": "assistant", "thinking": "ok", "content": "Hi"}, "done": False}),
            json.dumps({
                "model": "llama3.2",
                "message": {"role": "assistant", "content": " there"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            }),
        ]
        provider, client = _bind_ollama(OllamaProvider(model="llama3.2"), [
            _FakeOllamaResponse(lines=lines),
        ])

        async def drain():
            return [event async for event in provider.stream([], [], "sys")]

        events = asyncio.run(drain())
        assert client.requests[0]["json"]["stream"] is True
        assert [e.type for e in events] == [
            "thinking_delta", "thinking_delta", "text_delta", "text_delta", "done",
        ]
        done = events[-1].response
        assert done is not None
        assert done.content[0].text == "Hi there"
        assert done.thinking is not None
        assert done.thinking.thinking == "hmm ok"
        assert done.usage.input_tokens == 5
        assert done.usage.output_tokens == 3

    def test_stream_native_tool_calls(self):
        import asyncio
        import json

        from open_claude_code.providers.ollama import OllamaProvider

        tools = [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
        lines = [
            json.dumps({
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {"name": "echo", "arguments": {"message": "hi"}},
                    }],
                },
                "done": False,
            }),
            json.dumps({"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}),
        ]
        provider, _client = _bind_ollama(OllamaProvider(model="llama3.2"), [
            _FakeOllamaResponse(lines=lines),
        ])

        async def drain():
            return [event async for event in provider.stream([], tools, "sys")]

        events = asyncio.run(drain())
        types = [e.type for e in events]
        assert "tool_use_start" in types
        assert "tool_use_end" in types
        assert events[-1].type == "done"
        block = events[-1].response.content[0]
        assert block.name == "echo"
        assert block.input == {"message": "hi"}

    def test_model_not_found_is_clear(self):
        import asyncio

        import pytest

        from open_claude_code.providers.base import ProviderError
        from open_claude_code.providers.ollama import OllamaProvider

        provider, _client = _bind_ollama(OllamaProvider(model="missing"), [
            _FakeOllamaResponse(status_code=404, json_body={"error": "model 'missing' not found"}),
        ])
        with pytest.raises(ProviderError, match="ollama pull missing") as exc:
            asyncio.run(provider.send([], [], "sys"))
        assert exc.value.status_code == 404
        assert not exc.value.transient

    def test_connect_error_mentions_serve(self):
        import asyncio

        import httpx
        import pytest

        from open_claude_code.providers.base import ProviderError
        from open_claude_code.providers.ollama import OllamaProvider

        class _Boom:
            is_closed = False

            async def post(self, url, json=None):
                raise httpx.ConnectError("refused")

        provider = OllamaProvider(model="llama3.2")
        provider._client = _Boom()
        with pytest.raises(ProviderError, match="ollama serve"):
            asyncio.run(provider.send([], [], "sys"))

    def test_long_history_is_not_truncated(self):
        from open_claude_code.providers.ollama import OllamaProvider

        history = [{"role": "user", "content": f"turn {i}"} for i in range(40)]
        p = OllamaProvider(model="llama3.2")
        payload = p._payload(history, [], "sys", stream=True)
        user_msgs = [m for m in payload["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 40
        assert user_msgs[-1]["content"] == "turn 39"
