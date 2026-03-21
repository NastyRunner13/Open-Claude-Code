"""CLI entry point — wires up the agent with middleware and runs the REPL."""

from __future__ import annotations

import argparse
import asyncio
import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession, HTML

from open_claude_code import __version__
from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig, load_config, save_config
from open_claude_code.events import EventBus
from open_claude_code.listeners import (
    register_approval_listener,
    register_logging_listeners,
    register_ui_listeners,
)
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.middleware.mcp import MCPMiddleware
from open_claude_code.middleware.memory import MemoryMiddleware
from open_claude_code.middleware.skills import SkillsMiddleware
from open_claude_code.modes import run_mode
from open_claude_code.planning import PlanningMiddleware
from open_claude_code.providers import ProviderError, create_provider
from open_claude_code.system_prompt import MODE_PROMPTS
from open_claude_code.tools import get_tools

console = Console()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Open Claude Code — an open-source AI coding agent",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file (default: auto-detect occ.yml)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use (overrides config file)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Max tokens for model response (overrides config file)",
    )
    parser.add_argument(
        "--mode",
        choices=["ask", "plan", "agent"],
        default=None,
        help="Interaction mode: ask (no tools), plan (plan then execute), agent (full auto)",
    )
    parser.add_argument(
        "--skip-approval",
        action="store_true",
        default=None,
        help="Auto-approve all tool calls (skip y/n prompts)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the model provider (overrides env vars)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Custom API base URL (for OpenAI-compatible endpoints like OpenRouter)",
    )
    return parser.parse_args()


def resolve_config(args: argparse.Namespace) -> AgentConfig:
    """Merge config file, env vars, and CLI flags into final config."""
    config = load_config(args.config)

    # CLI and env overrides
    if args.model:
        config.model = args.model
    elif env_model := os.environ.get("OCC_MODEL"):
        config.model = env_model

    if args.max_tokens is not None:
        config.max_tokens = args.max_tokens

    if args.mode:
        config.mode = args.mode

    if args.skip_approval:
        config.skip_approval = True

    if args.api_key:
        config.api_key = args.api_key

    if args.base_url:
        config.base_url = args.base_url

    return config


def print_splash(config: AgentConfig, middleware_mgr: "MiddlewareManager | None" = None) -> None:
    """Print the Claude Code-inspired welcome banner.

    Layout:
      ┌─────────── Open Claude Code v0.1.0 ───────────┐
      │                                                │
      │        ██████╗   ██████╗  ██████╗              │
      │       ██╔═══██╗ ██╔════╝ ██╔════╝              │
      │       ██║   ██║ ██║      ██║                   │
      │       ╚██████╔╝ ╚██████╗ ╚██████╗              │
      │        ╚═════╝   ╚═════╝  ╚═════╝              │
      │                                                │
      │  Model · Mode · /working/dir                   │
      │                                                │
      │  Active middleware    │  Quick start            │
      │  ✓ MCP (2 servers)   │  /help for commands     │
      │  ✓ Skills (3 loaded) │  /mode to switch        │
      │  ✓ Memory            │  /plan to plan           │
      └────────────────────────────────────────────────┘
    """


    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]

    # ── ASCII art "OCC" ──────────────────────────────────────────
    OCC_ART = [
        " ██████╗   ██████╗  ██████╗ ",
        "██╔═══██╗ ██╔════╝ ██╔════╝ ",
        "██║   ██║ ██║      ██║      ",
        "██║   ██║ ██║      ██║      ",
        "╚██████╔╝ ╚██████╗ ╚██████╗ ",
        " ╚═════╝   ╚═════╝  ╚═════╝ ",
    ]

    # Gradient colors for the ASCII art rows (cyan → blue)
    art_colors = [
        "#00e5ff",  # bright cyan
        "#00d4ff",
        "#00bfff",  # deep sky blue
        "#00aaff",
        "#0095ff",
        "#0080ff",  # bright blue
    ]

    # ── Mode badge ───────────────────────────────────────────────
    mode_config = {
        "ask": ("?", "bold yellow"),
        "plan": ("📋", "bold magenta"),
        "agent": ("⚡", "bold green"),
    }
    mode_icon, mode_style = mode_config.get(config.mode, ("❯", "bold cyan"))

    # ── Build the splash content ─────────────────────────────────
    splash = Text()

    # ASCII art block
    for i, line in enumerate(OCC_ART):
        splash.append("    " + line + "\n", style=f"bold {art_colors[i]}")

    splash.append("\n")

    # Model · Mode · Directory info line (centered feel)
    splash.append("    ", style="dim")
    splash.append(config.model, style="bold white")
    splash.append(" · ", style="dim")
    splash.append(f"{mode_icon} {config.mode}", style=mode_style)
    splash.append(" · ", style="dim")
    splash.append("Max ", style="dim")
    splash.append(f"{config.max_tokens // 1000}k", style="bold white")
    splash.append("\n", style="dim")
    splash.append("    ", style="dim")
    splash.append(cwd, style="dim")

    # ── Middleware status (right column) ─────────────────────────
    right = Text()
    right.append("Active middleware\n", style="bold bright_green")

    if middleware_mgr:
        mw_list = middleware_mgr.middlewares if hasattr(middleware_mgr, 'middlewares') else []
        for mw in mw_list:
            name = getattr(mw, 'name', type(mw).__name__.replace('Middleware', ''))
            # Try to get extra info
            detail = ""
            if hasattr(mw, 'manager'):
                mgr = mw.manager
                if hasattr(mgr, 'servers') and mgr.servers:
                    detail = f" ({len(mgr.servers)} server{'s' if len(mgr.servers) != 1 else ''})"
                elif hasattr(mgr, '_loaded_skills'):
                    count = len(mgr._loaded_skills)
                    detail = f" ({count} loaded)" if count else ""
                elif hasattr(mgr, '_files'):
                    count = len(mgr._files)
                    detail = f" ({count} file{'s' if count != 1 else ''})" if count else ""
            right.append("  ✓ ", style="bright_green")
            right.append(f"{name}{detail}\n", style="white")
    else:
        right.append("  ─ none\n", style="dim")

    right.append("\n")
    right.append("Quick start\n", style="bold bright_yellow")
    right.append("  /help  ", style="bold white")
    right.append("for commands\n", style="dim")
    right.append("  /mode  ", style="bold white")
    right.append("switch modes\n", style="dim")
    right.append("  /plan  ", style="bold white")
    right.append("create a plan\n", style="dim")

    # ── Combine in columns ───────────────────────────────────────
    layout = Table.grid(padding=(0, 4))
    layout.add_column(ratio=3)
    layout.add_column(ratio=2)
    layout.add_row(splash, right)

    panel = Panel(
        layout,
        title=f"[bold bright_cyan]⚡ Open Claude Code[/] [dim]v{__version__}[/]",
        subtitle="[dim italic]open-source AI coding agent[/]",
        border_style="bright_cyan",
        padding=(1, 2),
        title_align="center",
        subtitle_align="center",
    )
    console.print()
    console.print(panel)
    console.print()


async def handle_slash_command(
    user_input: str,
    config: AgentConfig,
    agent: Agent,
    middleware_mgr: MiddlewareManager,
) -> str | None:
    """Handle slash commands. Returns:
      - None if not handled (pass through to mode router)
      - "handled" if fully handled (no further processing)
      - "ask:<text>" / "plan:<text>" / "agent:<text>" for one-shot mode routing
    """
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        console.print()
        help_table = Table(show_header=True, header_style="bold cyan")
        help_table.add_column("Command", style="bold")
        help_table.add_column("Description")
        help_table.add_row("/ask <question>", "Quick answer — no tools, single response")
        help_table.add_row("/plan <task>", "Create plan → review → execute")
        help_table.add_row("/agent <task>", "Full agent mode with tools")
        help_table.add_row("/mode", "Show current mode")
        help_table.add_row("/mode <mode>", "Switch default mode (ask | plan | agent)")
        help_table.add_row("/skill", "Manage skills (list | load <name> | unload <name> | reload)")
        help_table.add_row("/mcp", "Manage MCP servers (list | add <name> <cmd> [args] | remove <name>)")
        help_table.add_row("/plan show", "Show current plan/checklist")
        help_table.add_row("/plan progress", "Show plan progress bar")
        help_table.add_row("/plan clear", "Clear the current plan")
        help_table.add_row("/memory", "List loaded memory files (AGENTS.md, CLAUDE.md, etc.)")
        help_table.add_row("/memory reload", "Rescan for memory files")
        help_table.add_row("/memory show", "Preview loaded memory content")
        help_table.add_row("/clear", "Clear conversation history")
        help_table.add_row("/help", "Show this help")
        console.print(help_table)
        console.print()
        return "handled"

    if cmd == "/mode":
        if rest and rest in ("ask", "plan", "agent"):
            old_mode = config.mode
            config.mode = rest
            agent.system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])
            console.print(f"  Mode: {old_mode} → [bold cyan]{config.mode}[/]")
        else:
            mode_style = {"ask": "yellow", "plan": "magenta", "agent": "green"}.get(
                config.mode, "cyan"
            )
            console.print(f"  Current mode: [bold {mode_style}]{config.mode}[/]")
        console.print()
        return "handled"

    if cmd == "/clear":
        agent.history.clear()
        console.print("  Conversation history cleared.", style="dim")
        console.print()
        return "handled"

    # Try middleware slash commands
    mw_result = await middleware_mgr.handle_slash_command(cmd, rest)
    if mw_result is not None:
        # Handle async MCP operations
        if mw_result.startswith("mcp_async:"):
            mcp_mw = middleware_mgr.get("mcp")
            if mcp_mw and hasattr(mcp_mw, "handle_async_command"):
                await mcp_mw.handle_async_command(mw_result[10:])
                # Refresh tools after MCP changes
                agent.tools.update(middleware_mgr.collect_tools())
            return "handled"
        return mw_result

    # One-shot mode commands: /ask <text>, /plan <text>, /agent <text>
    if cmd in ("/ask", "/plan", "/agent") and rest:
        mode = cmd[1:]  # strip leading /
        return f"{mode}:{rest}"

    return None


async def run() -> None:
    """Main async entry point."""
    args = parse_args()
    config = resolve_config(args)

    # Create provider
    provider = create_provider(
        model=config.model,
        max_tokens=config.max_tokens,
        api_key=config.api_key,
        base_url=config.base_url,
        prompt_caching=config.prompt_caching,
    )

    # Set up event bus and listeners
    event_bus = EventBus()
    register_ui_listeners(event_bus)
    register_approval_listener(event_bus, config=config)
    register_logging_listeners(event_bus)

    # Get system prompt for current mode
    system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])

    # Build middleware stack
    # Order matters: memory first (stable context), then planning, skills, MCP
    memory_mw = MemoryMiddleware(
        search_dirs=config.memory_dirs if config.memory_dirs else None
    )
    planning_mw = PlanningMiddleware()
    skills_mw = SkillsMiddleware(
        search_dirs=config.skills_dirs if config.skills_dirs else None
    )
    mcp_mw = MCPMiddleware(config=config)

    middleware_mgr = MiddlewareManager([memory_mw, planning_mw, skills_mw, mcp_mw])

    # Get base tools (without skills — handled by middleware now)
    tools = get_tools(skill_manager=skills_mw.manager)

    # Create agent with middleware
    agent = Agent(
        provider=provider,
        event_bus=event_bus,
        tools=tools,
        system_prompt=system_prompt,
        config=config,
        middleware_manager=middleware_mgr,
    )

    # Initialize middleware (connects MCP servers, etc.)
    await agent.initialize()

    # Legacy compat — attach managers for any code that still accesses them
    agent._skill_manager = skills_mw.manager
    agent._mcp_manager = mcp_mw.manager

    print_splash(config, middleware_mgr)

    session = PromptSession()

    try:
        # REPL loop
        while True:
            # Show mode indicator + plan progress in prompt
            mode_char = {"ask": "?", "plan": "📋", "agent": "❯"}.get(config.mode, "❯")
            pt_style = {"ask": "ansiyellow", "plan": "ansimagenta", "agent": "ansicyan"}.get(
                config.mode, "ansicyan"
            )

            # Add plan progress to prompt if active
            plan_hint = ""
            if planning_mw.store.is_active:
                done, total = planning_mw.store.progress
                plan_hint = f" <ansigreen>[{done}/{total}]</ansigreen>"

            try:
                # use prompt_async to play nicely with our async loop
                user_input = await session.prompt_async(
                    HTML(f"<{pt_style}><b>{mode_char}</b></{pt_style}>{plan_hint} ")
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\nGoodbye! 👋", style="dim")
                return

            stripped = user_input.strip()
            if not stripped:
                continue

            # Handle slash commands
            if stripped.startswith("/"):
                result = await handle_slash_command(stripped, config, agent, middleware_mgr)
                if result == "handled":
                    continue
                if result and ":" in result:
                    # One-shot mode: "ask:question" / "plan:task" / "agent:task"
                    mode, text = result.split(":", 1)
                    await run_mode(mode, agent, text)
                    console.print()
                    continue

            # Normal input — route through current default mode
            await run_mode(config.mode, agent, stripped)
            console.print()
    finally:
        await middleware_mgr.shutdown()


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\nGoodbye! 👋", style="dim")


if __name__ == "__main__":
    main()
