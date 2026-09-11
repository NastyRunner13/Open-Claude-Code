"""Sub-agent manager — handles lifecycle, concurrency, and event emission.

The agent.py loop delegates to this module when it encounters spawn_agent calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from open_claude_code.events import (
    EventBus,
    SubagentStart,
    SubagentStop,
)
from open_claude_code.providers.base import ToolUseBlock
from open_claude_code.tools.policy import ToolPolicy, clamp_permission_mode
from open_claude_code.subagents.registry import AgentRegistry

if TYPE_CHECKING:
    from open_claude_code.agent import Agent


class SubagentManager:
    """Manages creation and concurrent execution of sub-agents.

    Design decisions:
      - Sub-agents get their own EventBus (isolated from parent UI)
      - Sub-agents are read-only by default; their parent explicitly authorizes spawn
      - Sub-agents cannot spawn further sub-agents (no recursion)
      - Sub-agents share the parent's provider but get independent conversation history
      - Multiple sub-agents execute concurrently via asyncio.gather
    """

    def __init__(self, parent_agent: "Agent") -> None:
        self.parent = parent_agent
        search_dirs = parent_agent.config.agents_dirs if parent_agent.config else None
        self.registry = AgentRegistry(search_dirs=search_dirs)

    async def run(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Run sub-agents concurrently and return tool result dicts."""
        tasks = [self._run_one(block) for block in spawn_blocks]
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

    async def _run_one(self, block: ToolUseBlock) -> dict:
        """Run a single sub-agent task."""
        from open_claude_code.agent import Agent
        from open_claude_code.providers import create_provider
        from open_claude_code.sessions import SessionStore

        task = block.input.get("task", "")
        requested_name = str(block.input.get("agent_name", ""))
        definition = self.registry.get(requested_name) if requested_name else None
        if requested_name and definition is None:
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": f"Unknown subagent role '{requested_name}'. Available roles: {', '.join(self.registry.definitions) or 'none'}",
            }

        # The child never inherits recursive spawning. Definitions can narrow
        # its toolset further. Requested permission_mode is clamped to the
        # parent and cannot elevate.
        sub_tools = {k: v for k, v in self.parent.tools.items() if k != "spawn_agent"}
        if definition and definition.tools:
            allowed = set(definition.tools)
            sub_tools = {name: tool for name, tool in sub_tools.items() if name in allowed}

        requested_mode = str(block.input.get("permission_mode", ""))
        role_mode = definition.permission_mode if definition else "read-only"
        parent_mode = self.parent.tool_policy.mode
        policy_mode = clamp_permission_mode(requested_mode, parent_mode, role_mode)
        policy_base = ToolPolicy.from_config(self.parent.config)
        disallowed = tuple(dict.fromkeys((*policy_base.disallowed_tools, *(definition.disallowed_tools if definition else ()))))
        policy = ToolPolicy(mode=policy_mode, disallowed_tools=disallowed)

        max_turns = definition.max_turns if definition else 25
        try:
            if block.input.get("max_turns") is not None:
                max_turns = max(1, min(int(block.input["max_turns"]), 1000))
        except (TypeError, ValueError):
            pass

        sub_config = replace(self.parent.config) if self.parent.config else None
        if sub_config:
            sub_config.permission_mode = policy_mode
            sub_config.shell_policy = policy_mode
        model = definition.model if definition and definition.model else self.parent.provider.model_name
        sub_provider = self.parent.provider
        if sub_config and definition and definition.model and definition.model != self.parent.provider.model_name:
            sub_config.model = definition.model
            sub_provider = create_provider(
                model=sub_config.model,
                max_tokens=sub_config.max_tokens,
                api_key=sub_config.api_key,
                base_url=sub_config.base_url,
                prompt_caching=sub_config.prompt_caching,
            )
        elif sub_config:
            sub_config.model = model

        sub_session = None
        if self.parent.session_store and sub_config and sub_config.persist_sessions:
            sub_session = SessionStore.create(
                config=sub_config,
                model=model,
                mode="agent",
                parent_session_id=self.parent.session_store.session_id,
            )

        # A child gets an isolated event bus.  The parent's approval of the
        # spawn is the human gate; the child policy is the non-bypassable gate.
        sub_bus = EventBus()

        prompt = self.parent.system_prompt
        if definition and definition.system_prompt:
            prompt = f"{prompt}\n\n# Subagent Role: {definition.name}\n{definition.system_prompt}"

        sub_agent = Agent(
            provider=sub_provider,
            event_bus=sub_bus,
            tools=sub_tools,
            system_prompt=prompt,
            config=sub_config,
            tool_policy=policy,
            middleware_manager=self.parent.middleware,
            session_store=sub_session,
            max_turns=max_turns,
        )

        # Emit events on the PARENT bus so the parent UI sees them
        await self.parent.event_bus.emit(SubagentStart(task=task))

        try:
            result = await sub_agent.run(task)
        except Exception as e:
            result = f"Sub-agent error: {e}"
        finally:
            if sub_session:
                sub_session.close()

        await self.parent.event_bus.emit(SubagentStop(task=task, result=result))

        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result[:12000] + ("\n[Sub-agent output truncated]" if len(result) > 12000 else ""),
        }
