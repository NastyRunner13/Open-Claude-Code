"""CLI entry point — wires up the agent with listeners and runs the REPL."""

from __future__ import annotations

import argparse
import asyncio
import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from open_claude_code import __version__
from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig, load_config
from open_claude_code.events import EventBus
from open_claude_code.listeners import (
    register_approval_listener,
    register_logging_listeners,
    register_ui_listeners,
)
from open_claude_code.modes import run_mode
from open_claude_code.providers import ProviderError, create_provider
from open_claude_code.skills import SkillManager
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


def print_splash(config: AgentConfig) -> None:
    """Print the welcome banner."""
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]

    # Mode label with color
    mode_style = {
        "ask": "bold yellow",
        "plan": "bold magenta",
        "agent": "bold green",
    }.get(config.mode, "bold")

    info = Table.grid(padding=(0, 2))
    info.add_column()
    info.add_column(style="dim")
    info.add_row("model", config.model)
    info.add_row("mode", Text(config.mode, style=mode_style))
    info.add_row("cwd", cwd)

    panel = Panel(
        info,
        title=f"[bold cyan]Open Claude Code[/bold cyan] v{__version__}",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)
    console.print()

    # Show available slash commands
    hint = Text()
    hint.append("  Slash commands: ", style="dim")
    for i, cmd in enumerate(["/ask", "/plan", "/agent", "/mode", "/clear", "/help"]):
        if i > 0:
            hint.append(" · ", style="dim")
        hint.append(cmd, style="bold cyan")
    console.print(hint)
    console.print()


def handle_slash_command(
    user_input: str,
    config: AgentConfig,
    agent: Agent,
) -> str | None:
    """Handle non-mode slash commands. Returns:
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

    if cmd == "/skill":
        # Requires the skill_manager to be attached to the agent
        sm = getattr(agent, '_skill_manager', None)
        if sm is None:
            console.print("  Skill system not initialized.", style="dim red")
        elif rest == "list" or not rest:
            console.print(f"  {sm.list_formatted()}")
        elif rest == "reload":
            sm.rescan()
            console.print("  Skills rescanned.", style="dim")
        elif rest.startswith("load "):
            name = rest[5:].strip()
            skill = sm.load(name)
            if skill:
                agent.system_prompt = MODE_PROMPTS.get(
                    getattr(agent, '_current_mode', 'agent'), 'agent'
                ) + sm.get_prompt_additions()
                console.print(f"  Loaded skill: [bold cyan]{skill.name}[/]")
            else:
                console.print(f"  Skill '{name}' not found.", style="dim red")
        elif rest.startswith("unload "):
            name = rest[7:].strip()
            if sm.unload(name):
                agent.system_prompt = MODE_PROMPTS.get(
                    getattr(agent, '_current_mode', 'agent'), 'agent'
                ) + sm.get_prompt_additions()
                console.print(f"  Unloaded skill: [bold]{name}[/]")
            else:
                console.print(f"  Skill '{name}' is not loaded.", style="dim red")
        else:
            console.print("  Usage: /skill [list|load <name>|unload <name>|reload]")
        console.print()
        return "handled"

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
    )

    # Set up event bus and listeners
    event_bus = EventBus()
    register_ui_listeners(event_bus)
    register_approval_listener(event_bus, config=config)
    register_logging_listeners(event_bus)

    # Get system prompt for current mode
    system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])

    # Initialize skill manager
    skill_manager = SkillManager(
        search_dirs=config.skills_dirs if config.skills_dirs else None
    )

    # Create agent
    agent = Agent(
        provider=provider,
        event_bus=event_bus,
        tools=get_tools(skill_manager=skill_manager),
        system_prompt=system_prompt,
        config=config,
    )
    # Attach skill manager for slash command access
    agent._skill_manager = skill_manager

    print_splash(config)

    # REPL loop
    while True:
        # Show mode indicator in prompt
        mode_char = {"ask": "?", "plan": "📋", "agent": "❯"}.get(config.mode, "❯")
        prompt_style = {"ask": "bold yellow", "plan": "bold magenta", "agent": "bold cyan"}.get(
            config.mode, "bold cyan"
        )

        try:
            user_input = console.input(f"[{prompt_style}]{mode_char}[/{prompt_style}] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye! 👋", style="dim")
            return

        stripped = user_input.strip()
        if not stripped:
            continue

        # Handle slash commands
        if stripped.startswith("/"):
            result = handle_slash_command(stripped, config, agent)
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


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\nGoodbye! 👋", style="dim")


if __name__ == "__main__":
    main()
