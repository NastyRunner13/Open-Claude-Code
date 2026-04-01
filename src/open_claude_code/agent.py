"""Core agent loop — conversation history, tool dispatch, event emission.

Contains ZERO UI or approval logic. All side effects go through the EventBus.
Supports an optional MiddlewareManager for composable feature injection.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from open_claude_code.events import (
    EventBus,
    PostToolUse,
    PreToolUse,
    Stop,
    StreamEnd,
    StreamStart,
    StreamTextDelta,
    StreamThinkingDelta,
    SubagentStart,
    SubagentStop,
    Thinking,
)
from open_claude_code.context import ContextManager
from open_claude_code.providers.base import (
    Provider,
    ProviderResponse,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
)
from open_claude_code.system_prompt import AGENT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig
    from open_claude_code.middleware import MiddlewareManager


class Agent:
    """The agent loop. Manages conversation, dispatches tools, emits events.

    The loop is deliberately kept pure — no UI, no approval logic.
    Everything flows through the EventBus.

    The optional MiddlewareManager provides composable feature injection:
    tools, prompt additions, and lifecycle hooks are all handled by middleware
    without modifying this core loop.
    """

    def __init__(
        self,
        provider: Provider,
        event_bus: EventBus,
        tools: dict | None = None,
        system_prompt: str = AGENT_SYSTEM_PROMPT,
        config: "AgentConfig | None" = None,
        middleware_manager: "MiddlewareManager | None" = None,
    ) -> None:
        self.provider = provider
        self.event_bus = event_bus
        self.tools = tools or {}
        self.system_prompt = system_prompt
        self.config = config
        self.history: list[dict] = []
        self.middleware = middleware_manager
        self._context_mgr = ContextManager(
            max_context_tokens=config.max_context_tokens if config else 100000,
            provider=provider,
        )

        # Derive auto-approve set from config
        self._auto_approve: set[str] = set()
        if config and config.auto_approve:
            self._auto_approve = set(config.auto_approve)

        # Planning tools are always auto-approved (they're non-destructive)
        self._auto_approve.update(["write_plan", "update_plan", "read_plan"])

    async def initialize(self) -> None:
        """Initialize middleware and merge tools/prompts.

        Call this after construction if using middleware.
        """
        if self.middleware:
            await self.middleware.startup(self)
            # Merge middleware tools into our tool registry
            self.tools.update(self.middleware.collect_tools())

    def _build_system_prompt(self) -> str:
        """Build the full system prompt including middleware additions."""
        base = self.system_prompt
        if self.middleware:
            additions = self.middleware.build_prompt_additions()
            if additions:
                base = f"{base}\n\n{additions}"
        return base

    async def run(self, user_input: str) -> str:
        """Run one turn of the agent loop. Returns the final text response."""
        # Let middleware transform input
        if self.middleware:
            user_input = await self.middleware.on_turn_start(user_input)

        self.history.append({"role": "user", "content": user_input})

        tool_schemas = [tool["schema"] for tool in self.tools.values()]
        system_prompt = self._build_system_prompt()

        while True:
            # Auto-compact history if approaching context limit
            self.history = await self._context_mgr.auto_compact_async(self.history)

            response: ProviderResponse = await self.provider.send(
                self.history, tool_schemas, system_prompt
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

                    # Convert ToolResult to string for display and LLM
                    result_str = str(result)

                    await self.event_bus.emit(
                        PostToolUse(
                            tool_name=block.name,
                            result=result_str,
                            tool_use_id=block.id,
                        )
                    )

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
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

                # Notify middleware of turn completion
                if self.middleware:
                    await self.middleware.on_turn_end(text)

                await self.event_bus.emit(Stop(text=text))
                return text

    async def run_streaming(self, user_input: str) -> str:
        """Run one turn with streaming. Tokens are emitted as they arrive.

        Falls back to non-streaming run() if the provider stream raises.
        """
        # Let middleware transform input
        if self.middleware:
            user_input = await self.middleware.on_turn_start(user_input)

        self.history.append({"role": "user", "content": user_input})

        tool_schemas = [tool["schema"] for tool in self.tools.values()]
        system_prompt = self._build_system_prompt()

        while True:
            self.history = await self._context_mgr.auto_compact_async(self.history)

            # Stream tokens from the provider
            await self.event_bus.emit(StreamStart())

            response: ProviderResponse | None = None
            full_text_parts: list[str] = []
            thinking_parts: list[str] = []

            try:
                async for event in self.provider.stream(
                    self.history, tool_schemas, system_prompt
                ):
                    if event.type == "text_delta":
                        full_text_parts.append(event.text)
                        await self.event_bus.emit(StreamTextDelta(text=event.text))

                    elif event.type == "thinking_delta":
                        thinking_parts.append(event.text)
                        await self.event_bus.emit(
                            StreamThinkingDelta(text=event.text)
                        )

                    elif event.type == "done":
                        response = event.response

            except Exception:
                # Fallback: remove the user message we added, delegate to run()
                self.history.pop()
                return await self.run(user_input)

            if response is None:
                # Should not happen, but guard
                self.history.pop()
                return await self.run(user_input)

            full_text = "".join(full_text_parts)
            await self.event_bus.emit(StreamEnd(full_text=full_text))

            # Emit thinking if present
            if response.thinking:
                await self.event_bus.emit(Thinking(text=response.thinking.thinking))

            tool_use_blocks = [
                b for b in response.content if isinstance(b, ToolUseBlock)
            ]
            text_blocks = [
                b for b in response.content if isinstance(b, TextBlock)
            ]

            if tool_use_blocks:
                # Build assistant message for history
                assistant_content = []
                if response.thinking:
                    assistant_content.append({
                        "type": "thinking",
                        "thinking": response.thinking.thinking,
                        "signature": response.thinking.signature,
                    })
                for block in response.content:
                    if isinstance(block, TextBlock):
                        assistant_content.append(
                            {"type": "text", "text": block.text}
                        )
                    elif isinstance(block, ToolUseBlock):
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                self.history.append(
                    {"role": "assistant", "content": assistant_content}
                )

                # Process tools (same logic as run())
                spawn_blocks = [
                    b for b in tool_use_blocks if b.name == "spawn_agent"
                ]
                regular_blocks = [
                    b for b in tool_use_blocks if b.name != "spawn_agent"
                ]

                tool_results = []

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

                    result_str = str(result)

                    await self.event_bus.emit(
                        PostToolUse(
                            tool_name=block.name,
                            result=result_str,
                            tool_use_id=block.id,
                        )
                    )

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

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
                    self.history.append(
                        {"role": "assistant", "content": assistant_content}
                    )
                else:
                    self.history.append(
                        {"role": "assistant", "content": text}
                    )

                if self.middleware:
                    await self.middleware.on_turn_end(text)

                await self.event_bus.emit(Stop(text=text))
                return text

    async def _run_subagents(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Run sub-agents concurrently via the SubagentManager."""
        from open_claude_code.subagents import SubagentManager
        manager = SubagentManager(self)
        return await manager.run(spawn_blocks)
