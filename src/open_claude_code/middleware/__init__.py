"""Composable middleware architecture for the agent.

Middleware can inject tools, extend system prompts, and hook into agent lifecycle
events — without knowing about other middleware. Inspired by DeepAgents' middleware
pattern but adapted for OCC's event-driven architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from open_claude_code.agent import Agent


class Middleware(ABC):
    """Base class for composable agent middleware.

    Subclass this to add features (tools, prompt additions, lifecycle hooks)
    to the agent without modifying core code.

    Lifecycle order:
      1. on_agent_start()  — called once when agent is first created
      2. get_tools()       — called to collect middleware tools
      3. get_prompt_additions() — called to build system prompt
      4. on_turn_start()   — called before each LLM call
      5. on_turn_end()     — called after each turn completes
      6. on_shutdown()     — called when agent shuts down
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this middleware."""

    async def on_agent_start(self, agent: Agent) -> None:
        """Called once when the agent initializes. Use for setup."""

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return tools to register. Format: {name: {function, schema}}."""
        return {}

    def get_prompt_additions(self) -> str:
        """Return text to append to the system prompt. Called each turn."""
        return ""

    async def on_turn_start(self, user_input: str) -> str:
        """Called before each LLM call. Can transform user input.

        Returns the (possibly modified) user input.
        """
        return user_input

    async def on_turn_end(self, response: str) -> None:
        """Called after each turn completes with the agent's response."""

    async def on_shutdown(self) -> None:
        """Called when the agent shuts down. Use for cleanup."""

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Handle a slash command. Return 'handled' if consumed, None otherwise."""
        return None


class MiddlewareManager:
    """Composes multiple middleware instances into a unified interface.

    Collects tools from all middleware, aggregates prompt additions,
    and dispatches lifecycle events to each middleware in order.
    """

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = middlewares or []
        self._agent: Agent | None = None

    @property
    def middlewares(self) -> list[Middleware]:
        """Return the list of registered middleware."""
        return self._middlewares

    def add(self, middleware: Middleware) -> None:
        """Add a middleware to the stack."""
        self._middlewares.append(middleware)

    def get(self, name: str) -> Middleware | None:
        """Get a middleware by name."""
        for mw in self._middlewares:
            if mw.name == name:
                return mw
        return None

    def collect_tools(self) -> dict[str, dict[str, Any]]:
        """Collect and merge tools from all middleware.

        Later middleware can override earlier middleware tools with the same name.
        """
        tools: dict[str, dict[str, Any]] = {}
        for mw in self._middlewares:
            tools.update(mw.get_tools())
        return tools

    def build_prompt_additions(self) -> str:
        """Build combined prompt additions from all middleware."""
        parts = []
        for mw in self._middlewares:
            addition = mw.get_prompt_additions()
            if addition and addition.strip():
                parts.append(addition.strip())
        return "\n\n".join(parts) if parts else ""

    async def startup(self, agent: Agent) -> None:
        """Initialize all middleware with the agent reference."""
        self._agent = agent
        for mw in self._middlewares:
            await mw.on_agent_start(agent)

    async def on_turn_start(self, user_input: str) -> str:
        """Run all middleware turn-start hooks. Returns transformed input."""
        current = user_input
        for mw in self._middlewares:
            current = await mw.on_turn_start(current)
        return current

    async def on_turn_end(self, response: str) -> None:
        """Run all middleware turn-end hooks."""
        for mw in self._middlewares:
            await mw.on_turn_end(response)

    async def shutdown(self) -> None:
        """Shut down all middleware (reverse order)."""
        for mw in reversed(self._middlewares):
            await mw.on_shutdown()

    async def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Try each middleware's slash command handler. First match wins."""
        for mw in self._middlewares:
            result = mw.handle_slash_command(cmd, rest)
            if result is not None:
                return result
        return None
