"""Tool call approval listener — prompts user with a styled y/n choice."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.text import Text

from open_claude_code.events import EventBus, PreToolUse

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig

console = Console()


def register_approval_listener(
    event_bus: EventBus,
    config: AgentConfig | None = None,
) -> None:
    """Register the approval listener.

    If config has skip_approval=True, all tools are auto-approved.
    Otherwise, tools not in auto_approve list will prompt the user.
    """

    async def on_pre_tool_use(event: PreToolUse) -> bool:
        if config and config.skip_approval:
            return True

        # If the tool doesn't require approval, auto-approve
        if not event.requires_approval:
            return True

        # Build a styled prompt
        prompt = Text()
        prompt.append("  ⚡ Allow ", style="bold")
        prompt.append(event.tool_name, style="bold bright_cyan")
        prompt.append("? ", style="bold")
        prompt.append("[", style="dim")
        prompt.append("Y", style="bold green")
        prompt.append("/", style="dim")
        prompt.append("n", style="red")
        prompt.append("] ", style="dim")
        console.print(prompt, end="")

        response = console.input("")
        # Default to yes (just pressing Enter approves)
        return response.strip().lower() != "n"

    event_bus.on_approval(on_pre_tool_use)
