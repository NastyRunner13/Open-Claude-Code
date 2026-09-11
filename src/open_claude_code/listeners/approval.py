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

        # Build a styled prompt. Privileged tools show the payload that matters.
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
        console.print()
        _print_approval_details(event.tool_name, event.tool_params)

        response = console.input("  ")
        # Default to yes (just pressing Enter approves)
        return response.strip().lower() != "n"


def _print_approval_details(tool_name: str, params: dict) -> None:
    """Show the command, spawn task, or write path before Y/n."""
    if tool_name == "run_shell":
        command = str(params.get("command", "")).strip()
        if command:
            console.print(f"    command: {command}", style="dim")
        return
    if tool_name == "spawn_agent":
        task = str(params.get("task", "")).strip()
        mode = str(params.get("permission_mode", "read-only") or "read-only")
        if task:
            shown = task if len(task) <= 200 else task[:199] + "…"
            console.print(f"    task: {shown}", style="dim")
        console.print(f"    permission_mode: {mode}", style="dim")
        return
    path = params.get("file_path") or params.get("path")
    if path:
        console.print(f"    path: {path}", style="dim")

    event_bus.on_approval(on_pre_tool_use)
