"""MemoryMiddleware — loads project-level memory files into the system prompt.

Discovers and loads files like AGENTS.md, .occ/memory.md, etc. from the
project directory. These files contain persistent knowledge about coding
conventions, architecture, preferences, and project-specific context.

Inspired by DeepAgents' MemoryMiddleware and Claude Code's CLAUDE.md system.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from open_claude_code.middleware import Middleware

if TYPE_CHECKING:
    from open_claude_code.agent import Agent

console = Console()

# Files to search for, in priority order
MEMORY_FILE_NAMES = [
    "AGENTS.md",
    "CLAUDE.md",
    "AI.md",
    ".occ/memory.md",
    ".occ/context.md",
    ".github/copilot-instructions.md",
]


class MemoryMiddleware(Middleware):
    """Middleware that loads project-level memory files into the system prompt.

    Memory files provide persistent, project-specific context:
    - Coding conventions and style guides
    - Architecture decisions and patterns
    - Team preferences and workflows
    - Known issues and gotchas

    The middleware scans the current directory (and optionally parent dirs)
    for recognized memory files and injects their contents into the prompt.
    """

    def __init__(
        self,
        search_dirs: list[str] | None = None,
        max_memory_chars: int = 8000,
    ) -> None:
        self._search_dirs = search_dirs or ["."]
        self._max_memory_chars = max_memory_chars
        self._loaded_files: dict[str, str] = {}  # path -> content
        self._agent: Agent | None = None

    @property
    def name(self) -> str:
        return "memory"

    @property
    def loaded_files(self) -> dict[str, str]:
        """Currently loaded memory files."""
        return dict(self._loaded_files)

    async def on_agent_start(self, agent: Agent) -> None:
        """Scan for and load memory files on startup."""
        self._agent = agent
        self._scan_and_load()

    def _scan_and_load(self) -> None:
        """Scan directories for memory files and load them."""
        self._loaded_files.clear()

        for search_dir in self._search_dirs:
            base = Path(search_dir).expanduser().resolve()
            if not base.exists():
                continue

            for filename in MEMORY_FILE_NAMES:
                filepath = base / filename
                if filepath.exists() and filepath.is_file():
                    try:
                        content = filepath.read_text(encoding="utf-8").strip()
                        if content:
                            rel_path = str(filepath.relative_to(base)) if filepath.is_relative_to(base) else str(filepath)
                            self._loaded_files[rel_path] = content
                    except Exception:
                        pass  # Skip unreadable files

        if self._loaded_files:
            total = sum(len(c) for c in self._loaded_files.values())
            files = ", ".join(self._loaded_files.keys())
            console.print(f"  📝 Loaded memory: {files} ({total:,} chars)", style="dim")

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """No tools — memory is prompt-only."""
        return {}

    def get_prompt_additions(self) -> str:
        """Inject loaded memory files into the system prompt."""
        if not self._loaded_files:
            return ""

        parts = ["## Project Memory"]
        parts.append(
            "The following project-level instructions were loaded from memory files. "
            "Follow these conventions and guidelines when working on this project.\n"
        )

        total_chars = 0
        for filepath, content in self._loaded_files.items():
            remaining = self._max_memory_chars - total_chars
            if remaining <= 0:
                parts.append(f"\n_({len(self._loaded_files) - len(parts) + 2} more files truncated)_")
                break

            if len(content) > remaining:
                content = content[:remaining] + "\n\n_(truncated)_"

            parts.append(f"### From `{filepath}`\n")
            parts.append(content)
            parts.append("")  # blank line separator
            total_chars += len(content)

        return "\n".join(parts)

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Handle /memory slash commands."""
        if cmd != "/memory":
            return None

        if not rest or rest == "list":
            if not self._loaded_files:
                console.print("  No memory files loaded.", style="dim")
                console.print(
                    "  Create one of these files in your project:",
                    style="dim",
                )
                for name in MEMORY_FILE_NAMES[:4]:
                    console.print(f"    • {name}", style="dim")
            else:
                console.print("  Loaded memory files:")
                for filepath, content in self._loaded_files.items():
                    chars = len(content)
                    console.print(f"    • [bold cyan]{filepath}[/] ({chars:,} chars)")
            console.print()
            return "handled"

        if rest == "reload":
            self._scan_and_load()
            if self._loaded_files:
                console.print(
                    f"  Reloaded {len(self._loaded_files)} memory file(s).",
                    style="dim",
                )
            else:
                console.print("  No memory files found.", style="dim")
            console.print()
            return "handled"

        if rest == "show":
            if not self._loaded_files:
                console.print("  No memory files loaded.", style="dim")
            else:
                for filepath, content in self._loaded_files.items():
                    console.print(f"\n  [bold cyan]── {filepath} ──[/]")
                    # Show first 500 chars
                    preview = content[:500]
                    if len(content) > 500:
                        preview += f"\n\n… ({len(content) - 500:,} more chars)"
                    for line in preview.split("\n"):
                        console.print(f"  {line}")
            console.print()
            return "handled"

        console.print("  Usage: /memory [list | reload | show]", style="dim")
        console.print()
        return "handled"
