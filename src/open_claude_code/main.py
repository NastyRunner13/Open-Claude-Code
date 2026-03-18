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

    if hasattr(args, 'api_key') and args.api_key:
        config.api_key = args.api_key

    if hasattr(args, 'base_url') and args.base_url:
        config.base_url = args.base_url

    return config


def print_splash(config: AgentConfig) -> None:
    """Print the welcome banner."""
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]

    info = Table.grid(padding=(0, 2))
    info.add_column()
    info.add_column(style="dim")
    info.add_row("model", config.model)
    info.add_row("mode", config.mode)
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
    hint.append("/ask", style="bold cyan")
    hint.append(" · ", style="dim")
    hint.append("/plan", style="bold cyan")
    hint.append(" · ", style="dim")
    hint.append("/agent", style="bold cyan")
    hint.append(" · ", style="dim")
    hint.append("/mode", style="bold cyan")
    hint.append(" · ", style="dim")
    hint.append("/help", style="bold cyan")
    console.print(hint)
    console.print()


def handle_slash_command(user_input: str, config: AgentConfig, agent: Agent) -> bool:
    """Handle slash commands. Returns True if handled, False otherwise."""
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/help":
        console.print()
        help_table = Table(show_header=True, header_style="bold cyan")
        help_table.add_column("Command", style="bold")
        help_table.add_column("Description")
        help_table.add_row("/ask <question>", "Ask a question (no tools, single response)")
        help_table.add_row("/plan <task>", "Create a plan before executing")
        help_table.add_row("/agent <task>", "Full agent mode with tools (default)")
        help_table.add_row("/mode", "Show current mode")
        help_table.add_row("/mode <mode>", "Switch default mode")
        help_table.add_row("/clear", "Clear conversation history")
        help_table.add_row("/help", "Show this help")
        console.print(help_table)
        console.print()
        return True

    if cmd == "/mode":
        if len(parts) > 1 and parts[1] in ("ask", "plan", "agent"):
            old_mode = config.mode
            config.mode = parts[1]
            agent.system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])
            console.print(f"  Mode: {old_mode} → [bold cyan]{config.mode}[/]")
        else:
            console.print(f"  Current mode: [bold cyan]{config.mode}[/]")
        console.print()
        return True

    if cmd == "/clear":
        agent.history.clear()
        console.print("  Conversation history cleared.", style="dim")
        console.print()
        return True

    if cmd in ("/ask", "/plan", "/agent"):
        # These are handled by the REPL — return False so they get processed
        return False

    return False


async def run() -> None:
    """Main async entry point."""
    args = parse_args()
    config = resolve_config(args)

    # Create provider
    provider = create_provider(
        model=config.model,
        max_tokens=config.max_tokens,
        api_key=getattr(config, 'api_key', None),
        base_url=getattr(config, 'base_url', None),
    )

    # Set up event bus and listeners
    event_bus = EventBus()
    register_ui_listeners(event_bus)
    register_approval_listener(event_bus, config=config)
    register_logging_listeners(event_bus)

    # Get system prompt for current mode
    system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])

    # Create agent
    agent = Agent(
        provider=provider,
        event_bus=event_bus,
        tools=get_tools(),
        system_prompt=system_prompt,
        config=config,
    )

    print_splash(config)

    # REPL loop
    while True:
        try:
            user_input = console.input("[bold cyan]❯[/bold cyan] ")
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye! 👋", style="dim")
            return

        stripped = user_input.strip()
        if not stripped:
            continue

        # Handle slash commands
        if stripped.startswith("/"):
            if handle_slash_command(stripped, config, agent):
                continue

            # Slash commands that submit to the agent
            parts = stripped.split(maxsplit=1)
            cmd = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else ""

            if cmd == "/ask" and rest:
                # Ask mode: use ask prompt, no tools
                original_prompt = agent.system_prompt
                original_tools = agent.tools
                agent.system_prompt = MODE_PROMPTS["ask"]
                agent.tools = {}
                try:
                    await agent.run(rest)
                except ProviderError as e:
                    console.print(f"  Error: {e}", style="bold red")
                finally:
                    agent.system_prompt = original_prompt
                    agent.tools = original_tools
                console.print()
                continue

            if cmd == "/plan" and rest:
                agent.system_prompt = MODE_PROMPTS["plan"]
                try:
                    await agent.run(rest)
                except ProviderError as e:
                    console.print(f"  Error: {e}", style="bold red")
                console.print()
                continue

            if cmd == "/agent" and rest:
                agent.system_prompt = MODE_PROMPTS["agent"]
                try:
                    await agent.run(rest)
                except ProviderError as e:
                    console.print(f"  Error: {e}", style="bold red")
                console.print()
                continue

        # Normal input — use current mode
        try:
            await agent.run(stripped)
            console.print()
        except ProviderError as e:
            console.print(f"  Error: {e}", style="bold red")
            console.print()


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\nGoodbye! 👋", style="dim")


if __name__ == "__main__":
    main()
