"""Plugin middleware that wires Python plugins into the agent runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from open_claude_code.config import AgentConfig
from open_claude_code.middleware import Middleware
from open_claude_code.plugins import PluginManager

if TYPE_CHECKING:
    from open_claude_code.agent import Agent
    from open_claude_code.providers.base import ProviderResponse

console = Console()


class PluginMiddleware(Middleware):
    """Load Python plugins and dispatch their lifecycle hooks."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config
        self._manager = PluginManager(
            search_dirs=config.plugins_dirs if config and config.plugins_dirs else None
        )
        self._agent: Agent | None = None

    @property
    def name(self) -> str:
        return "plugins"

    @property
    def manager(self) -> PluginManager:
        return self._manager

    async def on_agent_start(self, agent: Agent) -> None:
        self._agent = agent
        self._manager.scan_and_load()
        await self._manager.hooks.emit(
            "on_agent_start",
            agent=agent,
            config=agent.config,
        )

    async def on_before_send(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        current_messages = messages
        current_tools = tools

        for hook in self._manager.hooks.get_hooks("on_before_send"):
            result = await hook(messages=current_messages, tools=current_tools)
            if result is None:
                continue
            if isinstance(result, tuple) and len(result) == 2:
                current_messages, current_tools = result
            elif isinstance(result, dict):
                current_messages = result.get("messages", current_messages)
                current_tools = result.get("tools", current_tools)

        return current_messages, current_tools

    async def on_after_response(self, response: ProviderResponse) -> ProviderResponse:
        current = response
        for hook in self._manager.hooks.get_hooks("on_after_response"):
            result = await hook(response=current)
            if result is not None:
                current = result
        return current

    async def on_tool_result(
        self,
        tool_name: str,
        result: Any,
        tool_use_id: str = "",
    ) -> Any:
        current = result
        for hook in self._manager.hooks.get_hooks("on_tool_result"):
            hook_result = await hook(
                tool_name=tool_name,
                result=current,
                tool_use_id=tool_use_id,
            )
            if hook_result is not None:
                current = hook_result
        return current

    async def on_shutdown(self) -> None:
        await self._manager.hooks.emit("on_agent_stop", agent=self._agent)

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        if cmd != "/plugin":
            return None

        if not rest or rest == "list":
            console.print(self._manager.list_formatted())
            console.print()
            return "handled"

        if rest == "reload":
            self._manager = PluginManager(
                search_dirs=(
                    self._config.plugins_dirs
                    if self._config and self._config.plugins_dirs
                    else None
                )
            )
            loaded = self._manager.scan_and_load()
            console.print(f"  Reloaded {len(loaded)} plugin(s).")
            console.print()
            return "handled"

        console.print("  Usage: /plugin [list | reload]", style="dim")
        console.print()
        return "handled"
