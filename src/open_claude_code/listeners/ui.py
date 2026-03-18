"""Rich-based terminal UI event listeners.

The agent loop never calls UI code directly — everything goes through events.
This module provides a polished, premium terminal experience.
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.status import Status

from open_claude_code.events import (
    EventBus,
    AgentStart,
    Error,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,
    SubagentStop,
    Thinking,
)

MAX_RESULT_LINES = 12
MAX_THINKING = 300

console = Console()
_spinner: Status | None = None


# ── Formatting Helpers ─────────────────────────────────────────────

# Tool category colors
TOOL_COLORS = {
    "read_file": "bright_blue",
    "write_file": "bright_yellow",
    "edit_file": "bright_yellow",
    "list_directory": "bright_blue",
    "find_files": "bright_blue",
    "grep_search": "bright_cyan",
    "run_shell": "bright_magenta",
    "web_search": "bright_green",
    "read_url": "bright_green",
    "sandbox": "bright_magenta",
    "spawn_agent": "bright_red",
    "load_skill": "bright_cyan",
}

# Tool icons
TOOL_ICONS = {
    "read_file": "📄",
    "write_file": "✏️",
    "edit_file": "🔧",
    "list_directory": "📂",
    "find_files": "🔍",
    "grep_search": "🔎",
    "run_shell": "💻",
    "web_search": "🌐",
    "read_url": "🔗",
    "sandbox": "🧪",
    "spawn_agent": "🤖",
    "load_skill": "📦",
}


def _format_param_value(value: str | int | float | bool | list | dict, max_len: int = 50) -> str:
    """Format a parameter value for display."""
    if isinstance(value, str):
        if len(value) > max_len:
            return f'"{value[:max_len - 3]}…"'
        return f'"{value}"'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    text = json.dumps(value, separators=(",", ":"))
    if len(text) > max_len:
        return text[:max_len - 1] + "…"
    return text


def _format_tool_call(name: str, params: dict) -> Text:
    """Format tool call as a Rich Text object with syntax coloring."""
    color = TOOL_COLORS.get(name, "bright_white")
    icon = TOOL_ICONS.get(name, "●")

    line = Text()
    line.append(f"  {icon} ", style="bold")
    line.append(name, style=f"bold {color}")

    if not params:
        line.append("()", style="dim")
        return line

    # Format key parameters compactly
    line.append("(", style="dim")
    items = list(params.items())
    for i, (key, value) in enumerate(items[:3]):  # Show max 3 params
        if i > 0:
            line.append(", ", style="dim")
        line.append(key, style="dim italic")
        line.append("=", style="dim")
        line.append(_format_param_value(value), style="white")

    if len(items) > 3:
        line.append(f", …+{len(items) - 3}", style="dim")

    line.append(")", style="dim")
    return line


def _format_result_line(line: str) -> Text:
    """Format a single result line with tree-style prefix."""
    result = Text()
    result.append("  │ ", style="dim blue")
    result.append(line)
    return result


# ── Event Handlers ─────────────────────────────────────────────────

async def on_thinking(event: Thinking) -> None:
    """Render thinking as a subtle collapsible block, updating the spinner."""
    global _spinner
    text = event.text.strip().replace("\n", " ")
    if len(text) > MAX_THINKING:
        text = text[:MAX_THINKING] + "…"

    if _spinner:
        _spinner.update(f"[dim italic]{text}[/]")
    else:
        line = Text()
        line.append("  💭 ", style="dim")
        line.append(text, style="dim italic")
        console.print(line)


async def on_pre_tool_use(event: PreToolUse) -> None:
    """Render tool call with icon and syntax coloring."""
    global _spinner
    tool_text = _format_tool_call(event.tool_name, event.tool_params)
    console.print(tool_text)
    if _spinner:
        _spinner.update(f"[bold bright_magenta]Running tool:[/] {event.tool_name}...")


async def on_post_tool_use(event: PostToolUse) -> None:
    """Render tool result with tree-style indentation."""
    global _spinner
    if _spinner:
        _spinner.update("[dim]Analyzing results...[/]")

    result = event.result.strip()
    if not result:
        console.print("  │ ", style="dim blue")
        return

    lines = result.split("\n")
    visible_count = min(len(lines), MAX_RESULT_LINES)

    for line in lines[:visible_count]:
        console.print(_format_result_line(line))

    if len(lines) > MAX_RESULT_LINES:
        remaining = len(lines) - MAX_RESULT_LINES
        trunc_line = Text()
        trunc_line.append("  │ ", style="dim blue")
        trunc_line.append(f"… {remaining} more lines", style="dim italic")
        console.print(trunc_line)

    # End of tool output separator
    console.print("  │", style="dim blue")


async def on_stop(event: Stop) -> None:
    """Render final response as Rich Markdown in a clean panel."""
    global _spinner
    if _spinner:
        _spinner.stop()
        _spinner = None

    text = event.text.strip()
    if not text:
        return

    console.print()
    md = Markdown(text)
    console.print(Panel(
        md,
        border_style="bright_cyan",
        padding=(1, 2),
        title="[bold bright_cyan]Response[/]",
        title_align="left",
    ))


async def on_agent_start(event: AgentStart) -> None:
    """Start the spinner when the agent begins processing a request."""
    global _spinner
    if _spinner is None:
        _spinner = console.status("[dim]Thinking...[/]", spinner="dots")
        _spinner.start()


async def on_error(event: Error) -> None:
    """Stop spinner on error."""
    global _spinner
    if _spinner:
        _spinner.stop()
        _spinner = None
    
    console.print(f"[bold red]Error:[/] {event.message}")


async def on_subagent_start(event: SubagentStart) -> None:
    """Render sub-agent start with robot icon."""
    task = event.task[:80] + "…" if len(event.task) > 80 else event.task
    line = Text()
    line.append("  🤖 ", style="bold")
    line.append("Sub-agent: ", style="bold bright_red")
    line.append(task, style="italic")
    console.print(line)


async def on_subagent_stop(event: SubagentStop) -> None:
    """Render sub-agent completion."""
    task = event.task[:60] + "…" if len(event.task) > 60 else event.task
    line = Text()
    line.append("  │ ", style="dim blue")
    line.append("✓ ", style="bold green")
    line.append(f"done: {task}", style="dim")
    console.print(line)
    console.print()


# ── Registration ───────────────────────────────────────────────────

def register_ui_listeners(event_bus: EventBus) -> None:
    """Register all UI event listeners on the bus."""
    event_bus.on(AgentStart, on_agent_start)
    event_bus.on(Error, on_error)
    event_bus.on(Thinking, on_thinking)
    event_bus.on(PreToolUse, on_pre_tool_use)
    event_bus.on(PostToolUse, on_post_tool_use)
    event_bus.on(Stop, on_stop)
    event_bus.on(SubagentStart, on_subagent_start)
    event_bus.on(SubagentStop, on_subagent_stop)
