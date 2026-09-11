"""Core agent loop — conversation history, tool dispatch, event emission.

Contains ZERO UI or approval logic. All side effects go through the EventBus.
Supports an optional MiddlewareManager for composable feature injection.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from open_claude_code.events import (
    AgentStart,
    EventBus,
    PostToolUse,
    PreToolUse,
    Stop,
    StreamEnd,
    StreamStart,
    StreamTextDelta,
    StreamThinkingDelta,
    Thinking,
    ToolDenied,
    TokenDelta,
    ToolCallDelta,
    UsageUpdated,
    ProviderFailure,
)
from open_claude_code.context import ContextManager
from open_claude_code.providers.base import (
    Provider,
    ProviderResponse,
    ProviderError,
    TextBlock,
    ToolUseBlock,
)
from open_claude_code.system_prompt import AGENT_SYSTEM_PROMPT
from open_claude_code.tools.policy import ToolPolicy


if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig
    from open_claude_code.middleware import MiddlewareManager
    from open_claude_code.sessions import SessionStore


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
        tool_policy: ToolPolicy | None = None,
        session_store: "SessionStore | None" = None,
        max_turns: int | None = None,
    ) -> None:
        self.provider = provider
        self.event_bus = event_bus
        self.tools = tools or {}
        self.system_prompt = system_prompt
        self.config = config
        self.tool_policy = tool_policy or ToolPolicy.from_config(config)
        self.session_store = session_store
        self.max_turns = max(1, max_turns if max_turns is not None else (config.max_turns if config else 100))
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

        await self.event_bus.emit(
            AgentStart(
                task=user_input,
                mode=self.config.mode if self.config else "agent",
            )
        )

        self._append_history({"role": "user", "content": user_input})

        tool_schemas = [tool["schema"] for tool in self.tools.values()]
        system_prompt = self._build_system_prompt()

        turn_count = 0
        while True:
            if turn_count >= self.max_turns:
                raise ProviderError(f"agent exceeded configured maximum of {self.max_turns} provider turns")
            turn_count += 1
            # Auto-compact history if approaching context limit
            if not self.config or self.config.context_compaction:
                self.history = await self._context_mgr.auto_compact_async(self.history)

            provider_history = self.history
            provider_tool_schemas = tool_schemas
            if self.middleware:
                provider_history, provider_tool_schemas = await self.middleware.on_before_send(
                    provider_history,
                    provider_tool_schemas,
                )

            response = await self._stream_response(
                provider_history, provider_tool_schemas, system_prompt
            )
            if self.middleware:
                response = await self.middleware.on_after_response(response)

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
                self._append_history({"role": "assistant", "content": assistant_content})

                # Separate spawn_agent from regular tools
                spawn_blocks = [b for b in tool_use_blocks if b.name == "spawn_agent"]
                regular_blocks = [b for b in tool_use_blocks if b.name != "spawn_agent"]

                tool_results = []

                # Process regular tool calls.
                for block in regular_blocks:
                    approved, denied_result = await self._authorize_tool_call(block)

                    if approved and block.name in self.tools:
                        tool_fn = self.tools[block.name]["function"]
                        try:
                            result = await tool_fn(**block.input)
                        except Exception as e:
                            result = f"Error: {e}"
                    elif not approved:
                        result = denied_result
                    else:
                        result = f"Unknown tool: {block.name}"

                    if self.middleware:
                        result = await self.middleware.on_tool_result(
                            block.name,
                            result,
                            block.id,
                        )

                    # Convert ToolResult to string for display and LLM
                    result_str = str(result)

                    await self.event_bus.emit(
                        PostToolUse(
                            tool_name=block.name,
                            result=result_str,
                            tool_use_id=block.id,
                        )
                    )
                    if self.session_store:
                        self.session_store.record_tool_result(
                            block.name, block.id, result_str
                        )

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

                # The spawn itself is a privileged tool call.  Authorize every
                # requested child before starting the approved children in parallel.
                if spawn_blocks:
                    approved_spawns = []
                    for block in spawn_blocks:
                        approved, denied_result = await self._authorize_tool_call(block)
                        if approved:
                            approved_spawns.append(block)
                        else:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": denied_result,
                            })
                            if self.session_store:
                                self.session_store.record_tool_result(
                                    block.name, block.id, denied_result
                                )

                    spawn_results = await self._run_subagents(approved_spawns)
                    if self.session_store:
                        for result in spawn_results:
                            self.session_store.record_tool_result(
                                "spawn_agent",
                                result["tool_use_id"],
                                result["content"],
                            )
                    tool_results.extend(spawn_results)

                self._append_history({"role": "user", "content": tool_results})

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
                    self._append_history({"role": "assistant", "content": assistant_content})
                else:
                    self._append_history({"role": "assistant", "content": text})

                # Notify middleware of turn completion
                if self.middleware:
                    await self.middleware.on_turn_end(text)

                await self.event_bus.emit(Stop(text=text))
                return text

    async def _stream_response(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Consume the provider stream with bounded retry for transient failures."""
        retries = self.config.provider_max_retries if self.config else 2
        base_delay = self.config.provider_retry_base_delay if self.config else 0.5
        for attempt in range(retries + 1):
            try:
                return await self._consume_provider_stream(messages, tools, system_prompt)
            except ProviderError as error:
                if error.transient and attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    if self.session_store:
                        self.session_store.record(
                            "provider_retry",
                            {"attempt": attempt + 1, "delay_seconds": delay, "message": str(error)},
                        )
                    await asyncio.sleep(delay)
                    continue
                await self.event_bus.emit(
                    ProviderFailure(
                        message=str(error),
                        transient=error.transient,
                        status_code=error.status_code,
                    )
                )
                if self.session_store:
                    self.session_store.record(
                        "provider_error",
                        {"message": str(error), "transient": error.transient, "status_code": error.status_code},
                    )
                raise
            except Exception:
                # Preserve compatibility with providers that expose only
                # one-shot responses or whose streaming endpoint is disabled.
                return await self.provider.send(messages, tools, system_prompt)
        raise ProviderError("provider retry loop exited unexpectedly")

    async def _consume_provider_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> ProviderResponse:
        """Consume one provider stream while publishing normalized UI/ledger events."""
        final: ProviderResponse | None = None
        usage_emitted = False
        async for event in self.provider.stream(messages, tools, system_prompt):
            if event.type in {"content_delta", "text_delta"}:
                await self.event_bus.emit(TokenDelta(text=event.text, channel="content"))
                await self.event_bus.emit(StreamTextDelta(text=event.text))
                if self.session_store:
                    self.session_store.record("token_delta", {"channel": "content", "text": event.text})
            elif event.type == "thinking_delta":
                await self.event_bus.emit(TokenDelta(text=event.text, channel="thinking"))
                await self.event_bus.emit(StreamThinkingDelta(text=event.text))
                if self.session_store:
                    self.session_store.record("token_delta", {"channel": "thinking", "text": event.text})
            elif event.type in {"tool_call_delta", "tool_call_complete"} and getattr(event, "tool_call", None):
                await self.event_bus.emit(
                    ToolCallDelta(
                        tool_name=event.tool_call.name,
                        tool_use_id=event.tool_call.id,
                        complete=event.type == "tool_call_complete",
                    )
                )
            elif event.type in {"tool_use_start", "tool_use_end"}:
                await self.event_bus.emit(
                    ToolCallDelta(
                        tool_name=getattr(event, "tool_name", ""),
                        tool_use_id=getattr(event, "tool_id", ""),
                        complete=event.type == "tool_use_end",
                    )
                )
            elif event.type == "usage_delta" and event.usage:
                usage_emitted = True
                metadata = event.metadata
                usage_event = UsageUpdated(
                    input_tokens=event.usage.input_tokens,
                    output_tokens=event.usage.output_tokens,
                    cache_read_tokens=event.usage.cache_read_tokens,
                    cache_creation_tokens=event.usage.cache_creation_tokens,
                    request_id=metadata.request_id if metadata else "",
                    finish_reason=metadata.finish_reason if metadata else "",
                    latency_ms=metadata.latency_ms if metadata else 0.0,
                    model=metadata.model if metadata else "",
                )
                await self.event_bus.emit(usage_event)
                if self.session_store:
                    self.session_store.record("usage_updated", usage_event.__dict__)
            elif event.type in {"message_complete", "done"} and event.response:
                final = event.response
        if final is None:
            raise ProviderError("provider stream completed without a final response")
        if not usage_emitted:
            metadata = final.metadata
            usage_event = UsageUpdated(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
                cache_read_tokens=final.usage.cache_read_tokens,
                cache_creation_tokens=final.usage.cache_creation_tokens,
                request_id=metadata.request_id,
                finish_reason=metadata.finish_reason,
                latency_ms=metadata.latency_ms,
                model=metadata.model,
            )
            await self.event_bus.emit(usage_event)
            if self.session_store:
                self.session_store.record("usage_updated", usage_event.__dict__)
        return final

    def _append_history(self, message: dict) -> None:
        """Add one model-history item and persist it when a session is enabled."""
        self.history.append(message)
        if self.session_store:
            self.session_store.record_history(message)

    async def _authorize_tool_call(self, block: ToolUseBlock) -> tuple[bool, str]:
        """Apply non-bypassable policy, then obtain user approval if required."""
        decision = self.tool_policy.check_tool(block.name, block.input)
        if not decision.allowed:
            await self.event_bus.emit(
                ToolDenied(
                    tool_name=block.name,
                    reason=decision.reason,
                    operation=decision.operation,
                )
            )
            reason = f"Tool call denied by policy: {decision.reason}"
            if self.session_store:
                self.session_store.record_tool_call(
                    block.name, block.id, block.input, approved=False, reason=reason
                )
            return False, reason

        if self.middleware:
            hook_allowed, hook_reason = await self.middleware.on_before_tool(block.name, block.input)
            if not hook_allowed:
                await self.event_bus.emit(
                    ToolDenied(tool_name=block.name, reason=hook_reason, operation="hook")
                )
                reason = f"Tool call denied by hook: {hook_reason}"
                if self.session_store:
                    self.session_store.record_tool_call(
                        block.name, block.id, block.input, approved=False, reason=reason
                    )
                return False, reason

        requires_approval = block.name not in self._auto_approve
        approved = await self.event_bus.emit_approval(
            PreToolUse(
                tool_name=block.name,
                tool_params=block.input,
                requires_approval=requires_approval,
            )
        )
        if not approved:
            reason = "Tool call denied by user"
            if self.session_store:
                self.session_store.record_tool_call(
                    block.name, block.id, block.input, approved=False, reason=reason
                )
            return False, reason
        if self.session_store:
            self.session_store.record_tool_call(
                block.name, block.id, block.input, approved=True
            )
        return True, ""

    async def run_streaming(self, user_input: str) -> str:
        """Run a turn while publishing the legacy streaming UI events."""
        await self.event_bus.emit(StreamStart())
        text = await self.run(user_input)
        await self.event_bus.emit(StreamEnd(full_text=text))
        return text

    async def _run_subagents(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Run sub-agents concurrently via the SubagentManager."""
        from open_claude_code.subagents import SubagentManager
        manager = SubagentManager(self)
        return await manager.run(spawn_blocks)
