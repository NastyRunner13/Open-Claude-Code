"""SkillsMiddleware — wraps the existing SkillManager as composable middleware.

Delegates to the existing SkillManager for all skill logic, but exposes it
through the Middleware interface so it composes cleanly with other middleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from open_claude_code.middleware import Middleware
from open_claude_code.skills import SkillManager
from open_claude_code.tools.load_skill import SCHEMA as LOAD_SKILL_SCHEMA
from open_claude_code.tools.load_skill import load_skill

if TYPE_CHECKING:
    from open_claude_code.agent import Agent

console = Console()


class SkillsMiddleware(Middleware):
    """Middleware that integrates the skills system.

    - Injects the load_skill tool
    - Adds loaded skill instructions to the system prompt
    - Handles /skill slash commands
    """

    def __init__(self, search_dirs: list[str] | None = None) -> None:
        self._manager = SkillManager(search_dirs=search_dirs)
        self._agent: Agent | None = None

    @property
    def name(self) -> str:
        return "skills"

    @property
    def manager(self) -> SkillManager:
        """Access the underlying SkillManager."""
        return self._manager

    async def on_agent_start(self, agent: Agent) -> None:
        """Store agent reference for prompt updates."""
        self._agent = agent

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return the load_skill tool bound to our manager."""
        async def bound_load_skill(name: str) -> str:
            return await load_skill(name, _skill_manager=self._manager)

        return {
            "load_skill": {
                "function": bound_load_skill,
                "schema": LOAD_SKILL_SCHEMA,
            },
        }

    def get_prompt_additions(self) -> str:
        """Return loaded skill instructions for prompt injection."""
        return self._manager.get_prompt_additions()

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Handle /skill slash commands."""
        if cmd != "/skill":
            return None

        if rest == "list" or not rest:
            console.print(f"  {self._manager.list_formatted()}")
        elif rest == "reload":
            self._manager.rescan()
            console.print("  Skills rescanned.", style="dim")
        elif rest.startswith("load "):
            name = rest[5:].strip()
            skill = self._manager.load(name)
            if skill:
                console.print(f"  Loaded skill: [bold cyan]{skill.name}[/]")
            else:
                console.print(f"  Skill '{name}' not found.", style="dim red")
        elif rest.startswith("unload "):
            name = rest[7:].strip()
            if self._manager.unload(name):
                console.print(f"  Unloaded skill: [bold]{name}[/]")
            else:
                console.print(f"  Skill '{name}' is not loaded.", style="dim red")
        else:
            console.print("  Usage: /skill [list|load <name>|unload <name>|reload]")

        console.print()
        return "handled"
