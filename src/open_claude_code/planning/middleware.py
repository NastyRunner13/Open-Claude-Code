"""PlanningMiddleware — integrates the planning system into the agent.

Injects plan tools and adds plan context to the system prompt so the
agent always knows its current progress.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown

from open_claude_code.middleware import Middleware
from open_claude_code.planning.store import PlanStore
from open_claude_code.planning.tools import make_plan_tools

console = Console()


class PlanningMiddleware(Middleware):
    """Middleware that provides persistent planning/todo capabilities.

    - Injects write_plan, update_plan, read_plan tools
    - Adds current plan state to system prompt
    - Handles /plan slash commands
    """

    def __init__(self, store: PlanStore | None = None) -> None:
        self._store = store or PlanStore()
        self._tools = make_plan_tools(self._store)

    @property
    def name(self) -> str:
        return "planning"

    @property
    def store(self) -> PlanStore:
        """Access the underlying PlanStore."""
        return self._store

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return planning tools."""
        return self._tools

    def get_prompt_additions(self) -> str:
        """Inject current plan state into the system prompt."""
        if not self._store.is_active:
            return (
                "## Planning\n"
                "For complex multi-step tasks, use `write_plan` to create a structured "
                "checklist. Update items with `update_plan` as you work through them. "
                "This helps you track progress and stay organized."
            )

        return (
            "## Current Plan\n"
            f"{self._store.to_markdown()}\n\n"
            "**Instructions:** Update the plan as you work. Mark steps 'in_progress' "
            "when starting them and 'done' when complete. Use `update_plan` to track progress."
        )

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Handle /plan slash commands."""
        if cmd != "/plan":
            return None

        if not rest or rest == "show":
            console.print()
            if self._store.is_active:
                console.print(Markdown(self._store.to_markdown()))
            else:
                console.print("  No active plan.", style="dim")
            console.print()
            return "handled"

        if rest == "clear":
            self._store.title = ""
            self._store.items = []
            self._store._active = False
            console.print("  Plan cleared.", style="dim")
            console.print()
            return "handled"

        if rest == "progress":
            if self._store.is_active:
                done, total = self._store.progress
                pct = int((done / total) * 100) if total > 0 else 0
                bar_len = 20
                filled = int(bar_len * done / total) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_len - filled)
                console.print(f"  {bar}  {done}/{total} ({pct}%)", style="bold cyan")
            else:
                console.print("  No active plan.", style="dim")
            console.print()
            return "handled"

        console.print("  Usage: /plan [show | clear | progress]", style="dim")
        console.print()
        return "handled"
