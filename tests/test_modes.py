"""Tests for interaction modes (Ask, Plan, Agent)."""

import asyncio

from open_claude_code.agent import Agent
from open_claude_code.events import EventBus, Stop
from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock, ToolUseBlock
from open_claude_code.system_prompt import MODE_PROMPTS


class MockProvider(Provider):
    """Records calls and returns scripted responses."""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def send(self, messages, tools, system_prompt) -> ProviderResponse:
        self.calls.append({
            "messages": messages,
            "tools": tools,
            "system_prompt": system_prompt,
        })
        return self._responses.pop(0)


class TestAskMode:
    def test_ask_mode_no_tools(self):
        """Ask mode should not pass any tool schemas to the provider."""
        provider = MockProvider([
            ProviderResponse(thinking=None, content=[TextBlock(text="Python is amazing!")])
        ])

        bus = EventBus()
        agent = Agent(
            provider=provider, event_bus=bus, tools={"dummy": {"function": None, "schema": {"name": "dummy"}}},
            system_prompt=MODE_PROMPTS["agent"],
        )

        # Simulate ask mode: swap to ask prompt, clear tools
        original_tools = agent.tools
        agent.system_prompt = MODE_PROMPTS["ask"]
        agent.tools = {}

        result = asyncio.run(agent.run("what is python?"))

        assert result == "Python is amazing!"
        # Provider should have been called with empty tools list
        assert provider.calls[0]["tools"] == []
        # System prompt should be ask mode
        assert "ASK mode" in provider.calls[0]["system_prompt"]

        agent.tools = original_tools
        agent.system_prompt = MODE_PROMPTS["agent"]

    def test_ask_mode_preserves_history(self):
        """Ask mode responses are part of the conversation history."""
        provider = MockProvider([
            ProviderResponse(thinking=None, content=[TextBlock(text="It's a language.")])
        ])

        bus = EventBus()
        agent = Agent(provider=provider, event_bus=bus, tools={})
        agent.system_prompt = MODE_PROMPTS["ask"]

        asyncio.run(agent.run("what is python?"))

        assert len(agent.history) == 2
        assert agent.history[0]["role"] == "user"
        assert agent.history[1]["role"] == "assistant"


class TestAgentMode:
    def test_agent_mode_with_tools(self):
        """Agent mode should pass tools to the provider."""
        tool_schema = {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

        provider = MockProvider([
            ProviderResponse(thinking=None, content=[TextBlock(text="Done!")])
        ])

        bus = EventBus()
        agent = Agent(
            provider=provider, event_bus=bus,
            tools={"read_file": {"function": None, "schema": tool_schema}},
            system_prompt=MODE_PROMPTS["agent"],
        )

        result = asyncio.run(agent.run("read the file"))

        assert result == "Done!"
        assert len(provider.calls[0]["tools"]) == 1
        assert provider.calls[0]["tools"][0]["name"] == "read_file"


class TestPlanMode:
    def test_plan_mode_prompt(self):
        """Plan mode should use the plan system prompt."""
        provider = MockProvider([
            ProviderResponse(thinking=None, content=[TextBlock(text="Step 1: ...")])
        ])

        bus = EventBus()
        agent = Agent(
            provider=provider, event_bus=bus, tools={},
            system_prompt=MODE_PROMPTS["plan"],
        )

        result = asyncio.run(agent.run("refactor utils"))

        assert result == "Step 1: ..."
        assert "PLAN mode" in provider.calls[0]["system_prompt"]

    def test_plan_prompt_content(self):
        """Plan system prompt should instruct not to modify files."""
        assert "Do NOT make any file modifications" in MODE_PROMPTS["plan"]
        assert "numbered checklist" in MODE_PROMPTS["plan"]


class TestModePrompts:
    def test_all_modes_defined(self):
        """All three modes should have prompts defined."""
        assert "ask" in MODE_PROMPTS
        assert "plan" in MODE_PROMPTS
        assert "agent" in MODE_PROMPTS

    def test_agent_prompt_coding_first(self):
        """Agent prompt should emphasize coding-first identity."""
        assert "coding-first" in MODE_PROMPTS["agent"]

    def test_ask_prompt_no_tools(self):
        """Ask prompt should state no tools usage."""
        assert "without using any tools" in MODE_PROMPTS["ask"]
