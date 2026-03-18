"""Sub-agent manager — handles lifecycle, concurrency, and event emission.

The agent.py loop delegates to this module when it encounters spawn_agent calls.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from open_claude_code.events import (
    EventBus,
    PreToolUse,
    SubagentStart,
    SubagentStop,
)
from open_claude_code.providers.base import ToolUseBlock

if TYPE_CHECKING:
    from open_claude_code.agent import Agent


class SubagentManager:
    """Manages creation and concurrent execution of sub-agents.

    Design decisions:
      - Sub-agents get their own EventBus (isolated from parent UI)
      - Sub-agents auto-approve all tool calls (parent approval of spawn_agent is the gate)
      - Sub-agents cannot spawn further sub-agents (no recursion)
      - Sub-agents share the parent's provider but get independent conversation history
      - Multiple sub-agents execute concurrently via asyncio.gather
    """

    def __init__(self, parent_agent: "Agent") -> None:
        self.parent = parent_agent

    async def run(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Run sub-agents concurrently and return tool result dicts."""
        # Sub-agent tools = parent tools minus spawn_agent
        sub_tools = {k: v for k, v in self.parent.tools.items() if k != "spawn_agent"}

        tasks = [self._run_one(block, sub_tools) for block in spawn_blocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        final = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final.append({
                    "type": "tool_result",
                    "tool_use_id": spawn_blocks[i].id,
                    "content": f"Sub-agent error: {result}",
                })
            else:
                final.append(result)
        return final

    async def _run_one(self, block: ToolUseBlock, sub_tools: dict) -> dict:
        """Run a single sub-agent task."""
        from open_claude_code.agent import Agent

        task = block.input.get("task", "")

        # Sub-agent gets its own EventBus with auto-approve
        sub_bus = EventBus()

        async def auto_approve(_event: PreToolUse) -> bool:
            return True

        sub_bus.on_approval(auto_approve)

        sub_agent = Agent(
            provider=self.parent.provider,
            event_bus=sub_bus,
            tools=sub_tools,
            system_prompt=self.parent.system_prompt,
            config=self.parent.config,
        )

        # Emit events on the PARENT bus so the parent UI sees them
        await self.parent.event_bus.emit(SubagentStart(task=task))

        try:
            result = await sub_agent.run(task)
        except Exception as e:
            result = f"Sub-agent error: {e}"

        await self.parent.event_bus.emit(SubagentStop(task=task, result=result))

        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result,
        }
