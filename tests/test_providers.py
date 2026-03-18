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
