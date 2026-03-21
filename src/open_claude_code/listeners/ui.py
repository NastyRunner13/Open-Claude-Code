"""Rich-based terminal UI event listeners — Claude Code-inspired.

The agent loop never calls UI code directly — everything goes through events.
This module provides a polished, premium terminal experience with:
  - Compact tool call rendering with icons and dimmed params
  - Tree-style tool output with truncation
  - Progress indicator while the agent is thinking
  - Markdown panel for final responses
  - Plan progress display
"""

from __future__ import annotations

import json
import time

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
_turn_start_time: float | None = None
_tool_count: int = 0


# ── Formatting Helpers ─────────────────────────────────────────────

# Tool category colors — grouped by operation type
TOOL_COLORS = {
    # Read operations (blue family)
    "read_file": "bright_blue",
    "list_directory": "bright_blue",
    "find_files": "bright_blue",
    "grep_search": "bright_cyan",
    "read_plan": "bright_blue",
    # Write operations (yellow/amber family)
    "write_file": "bright_yellow",
    "edit_file": "bright_yellow",
    "write_plan": "#f59e0b",
    "update_plan": "#f59e0b",
    # Execution (magenta/purple)
    "run_shell": "bright_magenta",
    "sandbox": "bright_magenta",
    # Network (green)
    "web_search": "bright_green",
    "read_url": "bright_green",
    # Agent/meta (red/orange)
    "spawn_agent": "bright_red",
    "load_skill": "bright_cyan",
}

# Tool icons — compact, single-char where possible
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
    "write_plan": "📋",
    "update_plan": "✅",
    "read_plan": "📖",
}


def _format_param_value(value: str | int | float | bool | list | dict, max_len: int = 60) -> str:
    """Format a parameter value for display — compact and readable."""
    if isinstance(value, str):
        # Show file paths without quotes, truncate long strings
        if "/" in value or "\\" in value:
            if len(value) > max_len:
                return f"…{value[-(max_len - 1):]}"
            return value
        if len(value) > max_len:
            return f'"{value[:max_len - 3]}…"'
        return f'"{value}"'
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        if len(value) == 0:
            return "[]"
        # Show first item + count
        first = _format_param_value(value[0], max_len=30)
        if len(value) == 1:
            return f"[{first}]"
        return f"[{first}, …+{len(value) - 1}]"
    text = json.dumps(value, separators=(",", ":"))
    if len(text) > max_len:
        return text[:max_len - 1] + "…"
    return text


def _format_tool_call(name: str, params: dict) -> Text:
    """Format tool call as a compact, Claude Code-inspired line."""
    color = TOOL_COLORS.get(name, "bright_white")
    icon = TOOL_ICONS.get(name, "●")

    line = Text()
    line.append(f"  {icon} ", style="bold")
    line.append(name, style=f"bold {color}")

    if not params:
        return line

    # Show the most important parameter inline, rest dimmed
    # Priority: path/file_path > name > first param
    priority_keys = ["file_path", "path", "pattern", "command", "query", "title", "name", "url"]
    shown = []
    remaining = 0

    sorted_params = sorted(
        params.items(),
        key=lambda kv: (kv[0] not in priority_keys, priority_keys.index(kv[0]) if kv[0] in priority_keys else 99),
    )

    for key, value in sorted_params:
        if len(shown) < 2:
            shown.append((key, value))
        else:
            remaining += 1

    line.append("  ", style="dim")
    for i, (key, value) in enumerate(shown):
        if i > 0:
            line.append(" ", style="dim")
        formatted = _format_param_value(value)
        # First param is highlighted, rest dimmed
        if i == 0:
            line.append(formatted, style="white")
        else:
            line.append(f"{key}={formatted}", style="dim")

    if remaining > 0:
        line.append(f"  +{remaining}", style="dim")

    return line


def _format_result_line(line: str) -> Text:
    """Format a single result line with tree-style prefix."""
    result = Text()
    result.append("  │ ", style="dim bright_black")
    result.append(line)
    return result


def _elapsed_str() -> str:
    """Return elapsed time since turn started."""
    if _turn_start_time is None:
        return ""
    elapsed = time.time() - _turn_start_time
    if elapsed < 1:
        return ""
    if elapsed < 60:
        return f" [{elapsed:.0f}s]"
    return f" [{elapsed / 60:.0f}m{elapsed % 60:.0f}s]"


# ── Event Handlers ─────────────────────────────────────────────────

async def on_thinking(event: Thinking) -> None:
    """Render thinking as a subtle status update."""
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
    """Render tool call with compact Claude Code-style formatting."""
    global _spinner, _tool_count
    _tool_count += 1

    # Stop spinner temporarily to show tool call
    if _spinner:
        _spinner.stop()

    tool_text = _format_tool_call(event.tool_name, event.tool_params)
    console.print(tool_text)

    # Restart spinner with tool info
    if _spinner:
        _spinner.start()
        _spinner.update(f"[dim]Running {event.tool_name}…[/]")


async def on_post_tool_use(event: PostToolUse) -> None:
    """Render tool result with tree-style indentation."""
    global _spinner

    result = event.result.strip()
    if not result:
        return

    lines = result.split("\n")
    visible_count = min(len(lines), MAX_RESULT_LINES)

    for line in lines[:visible_count]:
        console.print(_format_result_line(line))

    if len(lines) > MAX_RESULT_LINES:
        remaining = len(lines) - MAX_RESULT_LINES
        trunc_line = Text()
        trunc_line.append("  │ ", style="dim bright_black")
        trunc_line.append(f"… {remaining} more lines", style="dim italic")
        console.print(trunc_line)

    # Visual separator after tool output
    console.print(Text("  │", style="dim bright_black"))

    # Resume spinner
    if _spinner:
        _spinner.update(f"[dim]Thinking…{_elapsed_str()}[/]")


async def on_stop(event: Stop) -> None:
    """Render final response as Rich Markdown in a clean panel."""
    global _spinner, _tool_count, _turn_start_time
    if _spinner:
        _spinner.stop()
        _spinner = None

    text = event.text.strip()
    if not text:
        return

    console.print()

    # Build subtitle with stats
    subtitle_parts = []
    if _tool_count > 0:
        subtitle_parts.append(f"{_tool_count} tool{'s' if _tool_count != 1 else ''}")
    if _turn_start_time:
        elapsed = time.time() - _turn_start_time
        if elapsed >= 1:
            if elapsed < 60:
                subtitle_parts.append(f"{elapsed:.1f}s")
            else:
                subtitle_parts.append(f"{elapsed / 60:.0f}m{elapsed % 60:.0f}s")
    subtitle = f"[dim]{' · '.join(subtitle_parts)}[/]" if subtitle_parts else ""

    md = Markdown(text)
    console.print(Panel(
        md,
        border_style="bright_cyan",
        padding=(1, 2),
        title="[bold bright_cyan]Response[/]",
        subtitle=subtitle,
        title_align="left",
        subtitle_align="right",
    ))

    # Reset turn counters
    _tool_count = 0
    _turn_start_time = None


async def on_agent_start(event: AgentStart) -> None:
    """Start the spinner when the agent begins processing a request."""
    global _spinner, _turn_start_time, _tool_count
    _turn_start_time = time.time()
    _tool_count = 0

    if _spinner is None:
        _spinner = console.status("[dim]Thinking…[/]", spinner="dots")
        _spinner.start()


async def on_error(event: Error) -> None:
    """Stop spinner and display error with helpful context."""
    global _spinner
    if _spinner:
        _spinner.stop()
        _spinner = None

    # Error panel with context
    error_text = Text()
    error_text.append("✗ ", style="bold red")
    error_text.append(event.message, style="red")

    if event.recoverable:
        error_text.append("\n\nThis error may be recoverable. Try again or rephrase.", style="dim")

    console.print(Panel(
        error_text,
        border_style="red",
        title="[bold red]Error[/]",
        title_align="left",
        padding=(0, 1),
    ))


async def on_subagent_start(event: SubagentStart) -> None:
    """Render sub-agent start with branching indicator."""
    task = event.task[:80] + "…" if len(event.task) > 80 else event.task
    line = Text()
    line.append("  ┌─ ", style="dim bright_magenta")
    line.append("🤖 ", style="bold")
    line.append("Sub-agent: ", style="bold bright_red")
    line.append(task, style="italic")
    console.print(line)


async def on_subagent_stop(event: SubagentStop) -> None:
    """Render sub-agent completion with closing branch."""
    task = event.task[:60] + "…" if len(event.task) > 60 else event.task
    line = Text()
    line.append("  └─ ", style="dim bright_magenta")
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
