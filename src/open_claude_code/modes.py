"""Mode router — Ask, Plan, and Agent mode logic.

Each mode encapsulates how user input is processed:
  - Ask:   Single LLM response, no tools, read-only
  - Plan:  LLM creates plan → user reviews → execute on approval
  - Agent: Full autonomous tool loop (default)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from open_claude_code.providers import ProviderError
from open_claude_code.system_prompt import MODE_PROMPTS

if TYPE_CHECKING:
    from open_claude_code.agent import Agent

console = Console()


# ── Ask Mode ──────────────────────────────────────────────────────

async def run_ask_mode(agent: Agent, user_input: str) -> None:
    """Ask mode — single response, no tools.

    Temporarily swaps the agent to ask-mode prompt with no tools,
    gets one response, then restores the original settings.
    """
    original_prompt = agent.system_prompt
    original_tools = agent.tools

    agent.system_prompt = MODE_PROMPTS["ask"]
    agent.tools = {}

    try:
        await agent.run(user_input)
    except ProviderError as e:
        console.print(f"  Error: {e}", style="bold red")
    finally:
        agent.system_prompt = original_prompt
        agent.tools = original_tools


# ── Plan Mode ─────────────────────────────────────────────────────

PLAN_PHASE_PROMPT = """\
You are Open Claude Code (OCC), an AI coding agent in PLAN mode.

The user has approved the following plan. Now execute it step-by-step.
After each major step, briefly report what you did. Do NOT ask for further \
approval — just execute the plan faithfully.

## Approved Plan
{plan}

## Original Task
{task}
"""


async def run_plan_mode(agent: Agent, user_input: str) -> None:
    """Plan mode:

    1. Agent creates a plan (using tools for exploration, but no modifications)
    2. Plan is displayed for user review
    3. User approves (y) or rejects (n) or refines (types feedback)
    4. If approved, agent executes the plan with full agent-mode tools
    """
    # Step 1: Generate the plan
    original_prompt = agent.system_prompt
    agent.system_prompt = MODE_PROMPTS["plan"]

    console.print()
    line = Text()
    line.append("  📋 ", style="bold")
    line.append("Plan Mode", style="bold cyan")
    line.append(" — generating plan for your task...", style="dim")
    console.print(line)
    console.print()

    try:
        plan_text = await agent.run(user_input)
    except ProviderError as e:
        console.print(f"  Error: {e}", style="bold red")
        agent.system_prompt = original_prompt
        return

    # Step 2: Ask for approval
    while True:
        console.print()
        approval_line = Text()
        approval_line.append("  Execute this plan? ", style="bold")
        approval_line.append("[y]es", style="green")
        approval_line.append(" / ", style="dim")
        approval_line.append("[n]o", style="red")
        approval_line.append(" / ", style="dim")
        approval_line.append("[type feedback to revise]", style="yellow")
        console.print(approval_line)

        try:
            response = console.input("  [bold cyan]❯[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("  Plan cancelled.", style="dim")
            agent.system_prompt = original_prompt
            return

        if not response:
            continue

        if response.lower() in ("y", "yes"):
            break

        if response.lower() in ("n", "no"):
            console.print("  Plan rejected.", style="dim red")
            agent.system_prompt = original_prompt
            return

        # User typed feedback — refine the plan
        console.print()
        console.print("  Refining plan...", style="dim italic")
        console.print()

        try:
            plan_text = await agent.run(response)
        except ProviderError as e:
            console.print(f"  Error: {e}", style="bold red")
            continue

    # Step 3: Execute the approved plan
    console.print()
    exec_line = Text()
    exec_line.append("  ▶ ", style="bold green")
    exec_line.append("Executing approved plan...", style="bold")
    console.print(exec_line)
    console.print()

    # Switch to agent mode for execution
    agent.system_prompt = PLAN_PHASE_PROMPT.format(plan=plan_text, task=user_input)

    try:
        await agent.run(
            "Execute the approved plan now. Work through each step and report progress."
        )
    except ProviderError as e:
        console.print(f"  Error during execution: {e}", style="bold red")
    finally:
        agent.system_prompt = original_prompt

    console.print()
    console.print("  ✅ Plan execution complete.", style="bold green")


# ── Agent Mode ────────────────────────────────────────────────────

async def run_agent_mode(agent: Agent, user_input: str) -> None:
    """Agent mode — full autonomous tool loop."""
    original_prompt = agent.system_prompt
    agent.system_prompt = MODE_PROMPTS["agent"]

    try:
        await agent.run(user_input)
    except ProviderError as e:
        console.print(f"  Error: {e}", style="bold red")
    finally:
        agent.system_prompt = original_prompt


# ── Mode Router ───────────────────────────────────────────────────

MODE_RUNNERS = {
    "ask": run_ask_mode,
    "plan": run_plan_mode,
    "agent": run_agent_mode,
}


async def run_mode(mode: str, agent: Agent, user_input: str) -> None:
    """Route to the appropriate mode handler."""
    runner = MODE_RUNNERS.get(mode, run_agent_mode)
    await runner(agent, user_input)
