"""Core agent loop — conversation history, tool dispatch, event emission.

Contains ZERO UI or approval logic. All side effects go through the EventBus.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from open_claude_code.events import (
    EventBus,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,
    SubagentStop,
    Thinking,
)
from open_claude_code.providers.base import (
    Provider,
    ProviderResponse,
    TextBlock,
    ToolUseBlock,
)
from open_claude_code.system_prompt import AGENT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig


class Agent:
    """The agent loop. Manages conversation, dispatches tools, emits events.

    The loop is deliberately kept pure — no UI, no approval logic.
    Everything flows through the EventBus.
    """

    def __init__(
        self,
        provider: Provider,
        event_bus: EventBus,
        tools: dict | None = None,
        system_prompt: str = AGENT_SYSTEM_PROMPT,
        config: "AgentConfig | None" = None,
    ) -> None:
        self.provider = provider
        self.event_bus = event_bus
        self.tools = tools or {}
        self.system_prompt = system_prompt
        self.config = config
        self.history: list[dict] = []

        # Derive auto-approve set from config
        self._auto_approve: set[str] = set()
        if config and config.auto_approve:
            self._auto_approve = set(config.auto_approve)

    async def run(self, user_input: str) -> str:
        """Run one turn of the agent loop. Returns the final text response."""
        self.history.append({"role": "user", "content": user_input})

        tool_schemas = [tool["schema"] for tool in self.tools.values()]

        while True:
            response: ProviderResponse = await self.provider.send(
                self.history, tool_schemas, self.system_prompt
            )

            # Emit thinking trace if present
            if response.thinking:
                await self.event_bus.emit(Thinking(text=response.thinking.thinking))

            tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
            text_blocks = [b for b in response.content if isinstance(b, TextBlock)]

            if tool_use_blocks:
                # Build assistant message — include thinking blocks for multi-turn
                assistant_content = []
                if response.thinking:
                    assistant_content.append({
                        "type": "thinking",
                        "thinking": response.thinking.thinking,
                        "signature": response.thinking.signature,
                    })
                for block in response.content:
                    if isinstance(block, TextBlock):
                        assistant_content.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                self.history.append({"role": "assistant", "content": assistant_content})

                # Separate spawn_agent from regular tools
                spawn_blocks = [b for b in tool_use_blocks if b.name == "spawn_agent"]
                regular_blocks = [b for b in tool_use_blocks if b.name != "spawn_agent"]

                tool_results = []

                # Process regular tool calls
                for block in regular_blocks:
                    requires_approval = block.name not in self._auto_approve

                    approved = await self.event_bus.emit_approval(
                        PreToolUse(
                            tool_name=block.name,
                            tool_params=block.input,
                            requires_approval=requires_approval,
                        )
                    )

                    if approved and block.name in self.tools:
                        tool_fn = self.tools[block.name]["function"]
                        try:
                            result = await tool_fn(**block.input)
                        except Exception as e:
                            result = f"Error: {e}"
                    elif not approved:
                        result = "Tool call denied by user"
                    else:
                        result = f"Unknown tool: {block.name}"

                    await self.event_bus.emit(
                        PostToolUse(
                            tool_name=block.name,
                            result=result,
                            tool_use_id=block.id,
                        )
                    )

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                # Process spawn_agent calls concurrently
                if spawn_blocks:
                    spawn_results = await self._run_subagents(spawn_blocks)
                    tool_results.extend(spawn_results)

                self.history.append({"role": "user", "content": tool_results})

            else:
                # Text-only response — we're done
                text = "\n".join(b.text for b in text_blocks)

                if response.thinking:
                    assistant_content = [
                        {
                            "type": "thinking",
                            "thinking": response.thinking.thinking,
                            "signature": response.thinking.signature,
                        },
                        {"type": "text", "text": text},
                    ]
                    self.history.append({"role": "assistant", "content": assistant_content})
                else:
                    self.history.append({"role": "assistant", "content": text})

                await self.event_bus.emit(Stop(text=text))
                return text

    async def _run_subagents(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Run sub-agents concurrently via the SubagentManager."""
        from open_claude_code.subagents import SubagentManager
        manager = SubagentManager(self)
        return await manager.run(spawn_blocks)

