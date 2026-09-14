"""Skill loader — discovers, parses, and manages SKILL.md files.

Skills are directories containing a SKILL.md file with YAML frontmatter
(name, description) and detailed instructions in markdown. When loaded,
skill instructions are injected into the agent's system prompt.

Skill directory structure:
  skills/
    my-skill/
      SKILL.md          # Required: frontmatter + instructions
      scripts/           # Optional: helper scripts
      examples/          # Optional: reference implementations
      assets/            # Optional: templates, fixtures, images
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

logger = logging.getLogger("occ.skills")


def _bundled_files(directory: Path) -> list[Path]:
    """Return regular files in *directory*, sorted, skipping hidden names."""
    if not directory.is_dir():
        return []
    return sorted(
        path.resolve()
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )


def _parse_allowed_tools(raw: object) -> list[str]:
    """Normalize `allowed_tools` / `allowed-tools` from YAML frontmatter."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part for part in raw.replace(",", " ").split() if part]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


@dataclass
class Skill:
    """A parsed skill with metadata and instructions."""

    name: str
    description: str
    instructions: str
    path: Path

    scripts: list[Path] = field(default_factory=list)
    examples: list[Path] = field(default_factory=list)
    assets: list[Path] = field(default_factory=list)
    disable_model_invocation: bool = False
    allowed_tools: list[str] = field(default_factory=list)

    def permits_tool(self, tool_name: str) -> bool:
        """True when this skill does not restrict tools, or *tool_name* matches."""
        if not self.allowed_tools:
            return True
        return any(fnmatchcase(tool_name, pattern) for pattern in self.allowed_tools)

    @property
    def prompt_injection(self) -> str:
        """Format skill for injection into the system prompt."""
        parts = [
            f"\n\n## Skill: {self.name}",
            self.description,
            "",
            "### Instructions",
            self.instructions,
        ]
        bundled = self._bundled_prompt()
        if bundled:
            parts.extend(["", bundled])
        if self.allowed_tools:
            parts.extend(
                [
                    "",
                    "### Allowed tools",
                    "This skill narrows available tools to: " + ", ".join(self.allowed_tools),
                    "Calls outside this list are denied. Unloading the skill restores the previous set.",
                    "allowed_tools cannot raise privilege above the session policy.",
                ]
            )
        return "\n".join(parts) + "\n"

    def _bundled_prompt(self) -> str:
        sections: list[str] = []
        for label, paths in (
            ("Scripts", self.scripts),
            ("Examples", self.examples),
            ("Assets", self.assets),
        ):
            if not paths:
                continue
            lines = [
                f"{label} (read_file / run_shell; do not assume they have already been executed):"
            ]
            lines.extend(f"- {path}" for path in paths)
            sections.append("\n".join(lines))
        if not sections:
            return ""
        return "### Bundled files\n" + "\n\n".join(sections)


def parse_skill_md(path: Path, include_instructions: bool = True) -> Skill:
    """Parse a SKILL.md file into a Skill object.

    Expected format:
    ---
    name: My Skill
    description: What the skill does
    allowed_tools: [read_file, grep_search]
    ---
    Detailed instructions in markdown...
    """
    content = path.read_text(encoding="utf-8")

    name = "unnamed"
    description = ""
    instructions = content if include_instructions else ""
    metadata: dict = {}

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            instructions = parts[2].strip() if include_instructions else ""

            try:
                import yaml
                parsed = yaml.safe_load(frontmatter)
                metadata = parsed if isinstance(parsed, dict) else {}
            except Exception as exc:
                logger.warning("invalid YAML frontmatter in %s: %s", path, exc)
                metadata = {}
            name = str(metadata.get("name", name))
            description = str(metadata.get("description", description))

    skill_dir = path.parent
    raw_allowed = metadata.get("allowed_tools", metadata.get("allowed-tools"))

    return Skill(
        name=name,
        description=description,
        instructions=instructions,
        path=skill_dir,
        scripts=_bundled_files(skill_dir / "scripts"),
        examples=_bundled_files(skill_dir / "examples"),
        assets=_bundled_files(skill_dir / "assets"),
        disable_model_invocation=bool(metadata.get("disable_model_invocation", False)),
        allowed_tools=_parse_allowed_tools(raw_allowed),
    )


class SkillManager:
    """Manages skill discovery, loading, and prompt injection."""

    def __init__(self, search_dirs: list[str] | None = None) -> None:
        self._search_dirs = [
            Path(d).expanduser() for d in (search_dirs or ["~/.occ/skills", ".occ/skills"])
        ]
        self._loaded: dict[str, Skill] = {}
        self._available: dict[str, Skill] = {}
        self._scan_warnings: list[str] = []
        self._scan()

    def _scan(self) -> None:
        """Scan search directories for available skills."""
        self._available.clear()
        self._scan_warnings.clear()
        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for skill_dir in search_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    # Keep discovery cheap: detailed instructions only
                    # enter prompt context after an explicit load.
                    skill = parse_skill_md(skill_md, include_instructions=False)
                except Exception as exc:
                    warning = f"skipping malformed skill {skill_md}: {exc}"
                    logger.warning(warning)
                    self._scan_warnings.append(warning)
                    continue
                self._available[skill.name] = skill

    def rescan(self) -> None:
        """Re-scan for available skills."""
        self._scan()

    @property
    def available(self) -> dict[str, Skill]:
        """All discovered skills."""
        return dict(self._available)

    @property
    def loaded(self) -> dict[str, Skill]:
        """Currently loaded (active) skills."""
        return dict(self._loaded)

    @property
    def scan_warnings(self) -> list[str]:
        """Human-readable reasons skills were skipped on the last scan."""
        return list(self._scan_warnings)

    def load(self, name: str) -> Skill | None:
        """Load a skill by name. Returns the skill or None if not found."""
        if name in self._loaded:
            return self._loaded[name]

        if name in self._available:
            self._loaded[name] = parse_skill_md(self._available[name].path / "SKILL.md")
            return self._loaded[name]

        path = Path(name).expanduser()
        if path.exists():
            skill_md = path / "SKILL.md" if path.is_dir() else path
            if skill_md.exists():
                skill = parse_skill_md(skill_md)
                self._loaded[skill.name] = skill
                return skill

        return None

    def unload(self, name: str) -> bool:
        """Unload a skill. Returns True if the skill was loaded."""
        return self._loaded.pop(name, None) is not None

    def tool_permitted(self, tool_name: str) -> bool:
        """True unless a loaded skill's allowed_tools excludes *tool_name*.

        Empty ``allowed_tools`` is not a restriction. Multiple restricting
        skills intersect. This never adds tools the session policy forbids.
        """
        return all(skill.permits_tool(tool_name) for skill in self._loaded.values())

    def restriction_reason(self, tool_name: str) -> str | None:
        """Explain why *tool_name* is blocked, or None if it is permitted."""
        blockers = [
            skill
            for skill in self._loaded.values()
            if not skill.permits_tool(tool_name)
        ]
        if not blockers:
            return None
        details = "; ".join(
            f"{skill.name}: {', '.join(skill.allowed_tools)}" for skill in blockers
        )
        return f"tool '{tool_name}' is outside loaded skill allowed_tools ({details})"

    def filter_tool_schemas(self, schemas: list[dict]) -> list[dict]:
        """Drop schemas the loaded skills do not allow the model to see."""
        if not any(skill.allowed_tools for skill in self._loaded.values()):
            return schemas
        return [schema for schema in schemas if self.tool_permitted(str(schema.get("name", "")))]

    def get_prompt_additions(self) -> str:
        """Get all loaded skill instructions for prompt injection."""
        if not self._loaded:
            return ""

        parts = ["\n\n# Loaded Skills"]
        for skill in self._loaded.values():
            parts.append(skill.prompt_injection)
        return "\n".join(parts)

    def get_catalog_prompt(self) -> str:
        """Expose a compact, model-invocable skill catalog without full bodies."""
        choices = [skill for skill in self._available.values() if not skill.disable_model_invocation]
        if not choices:
            return ""
        lines = ["# Available Skills", "Load a skill with `load_skill` only when it is relevant:"]
        for skill in choices:
            extra = ""
            if skill.allowed_tools:
                extra = f" (narrows tools to {', '.join(skill.allowed_tools)})"
            lines.append(f"- {skill.name}: {skill.description or 'No description provided.'}{extra}")
        return "\n".join(lines)

    def list_formatted(self) -> str:
        """Return a formatted listing of available and loaded skills."""
        lines = []

        if not self._available:
            lines.append("No skills found. Create skills in ~/.occ/skills/ or .occ/skills/")
            lines.append("")
            lines.append("Skill format: Create a directory with a SKILL.md file containing:")
            lines.append("  ---")
            lines.append("  name: My Skill")
            lines.append("  description: What the skill does")
            lines.append("  allowed_tools: [read_file, grep_search]  # optional; narrows, never elevates")
            lines.append("  ---")
            lines.append("  Detailed instructions...")
            if self._scan_warnings:
                lines.append("")
                lines.append("Skipped:")
                for warning in self._scan_warnings:
                    lines.append(f"  • {warning}")
            return "\n".join(lines)

        lines.append("Available Skills:")
        for name, skill in self._available.items():
            loaded = " [loaded]" if name in self._loaded else ""
            tools = f" (tools: {', '.join(skill.allowed_tools)})" if skill.allowed_tools else ""
            lines.append(f"  • {name} — {skill.description}{loaded}{tools}")
        if self._scan_warnings:
            lines.append("")
            lines.append("Skipped:")
            for warning in self._scan_warnings:
                lines.append(f"  • {warning}")

        return "\n".join(lines)
