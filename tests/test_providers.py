"""Tests for the provider registry and message conversion utilities."""

import os

import pytest

from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock
from open_claude_code.providers.registry import create_provider


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

    def test_groq_by_env_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
        p = create_provider("llama-3.3-70b-versatile")
        from open_claude_code.providers.groq import GroqProvider
        assert isinstance(p, GroqProvider)

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
