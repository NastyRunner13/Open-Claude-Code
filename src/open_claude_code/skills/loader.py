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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    """A parsed skill with metadata and instructions."""

    name: str
    description: str
    instructions: str
    path: Path

    # Additional file paths relative to the skill directory
    scripts: list[Path] = field(default_factory=list)
    examples: list[Path] = field(default_factory=list)

    @property
    def prompt_injection(self) -> str:
        """Format skill for injection into the system prompt."""
        return (
            f"\n\n## Skill: {self.name}\n"
            f"{self.description}\n\n"
            f"### Instructions\n"
            f"{self.instructions}\n"
        )


def parse_skill_md(path: Path) -> Skill:
    """Parse a SKILL.md file into a Skill object.

    Expected format:
    ---
    name: My Skill
    description: What the skill does
    ---
    Detailed instructions in markdown...
    """
    content = path.read_text(encoding="utf-8")

    # Parse YAML frontmatter
    name = "unnamed"
    description = ""
    instructions = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            instructions = parts[2].strip()

            # Simple YAML parsing (avoid full YAML dependency for just two fields)
            for line in frontmatter.split("\n"):
                line = line.strip()
                if line.startswith("name:"):
                    name = line[5:].strip().strip("\"'")
                elif line.startswith("description:"):
                    description = line[12:].strip().strip("\"'")

    skill_dir = path.parent

    # Discover additional resources
    scripts = list((skill_dir / "scripts").glob("*")) if (skill_dir / "scripts").exists() else []
    examples = list((skill_dir / "examples").glob("*")) if (skill_dir / "examples").exists() else []

    return Skill(
        name=name,
        description=description,
        instructions=instructions,
        path=skill_dir,
        scripts=scripts,
        examples=examples,
    )


class SkillManager:
    """Manages skill discovery, loading, and prompt injection."""

    def __init__(self, search_dirs: list[str] | None = None) -> None:
        self._search_dirs = [
            Path(d).expanduser() for d in (search_dirs or ["~/.occ/skills", ".occ/skills"])
        ]
        self._loaded: dict[str, Skill] = {}
        self._available: dict[str, Skill] = {}
        self._scan()

    def _scan(self) -> None:
        """Scan search directories for available skills."""
        self._available.clear()
        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for skill_dir in search_dir.iterdir():
                if skill_dir.is_dir():
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        try:
                            skill = parse_skill_md(skill_md)
                            self._available[skill.name] = skill
                        except Exception:
                            pass  # Skip malformed skills

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

    def load(self, name: str) -> Skill | None:
        """Load a skill by name. Returns the skill or None if not found."""
        # Check if already loaded
        if name in self._loaded:
            return self._loaded[name]

        # Check available skills
        if name in self._available:
            self._loaded[name] = self._available[name]
            return self._loaded[name]

        # Try loading from a direct path
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

    def get_prompt_additions(self) -> str:
        """Get all loaded skill instructions for prompt injection."""
        if not self._loaded:
            return ""

        parts = ["\n\n# Loaded Skills"]
        for skill in self._loaded.values():
            parts.append(skill.prompt_injection)
        return "\n".join(parts)

    def list_formatted(self) -> str:
        """Return a formatted listing of available and loaded skills."""
        lines = []

        if not self._available:
            lines.append("No skills found. Create skills in ~/.occ/skills/ or .occ/skills/")
            lines.append("")
            lines.append("Skill format: Create a directory with a SKILL.md file containing:")
            lines.append('  ---')
            lines.append('  name: My Skill')
            lines.append('  description: What the skill does')
            lines.append('  ---')
            lines.append('  Detailed instructions...')
            return "\n".join(lines)

        lines.append("Available Skills:")
        for name, skill in self._available.items():
            loaded = " [loaded]" if name in self._loaded else ""
            lines.append(f"  • {name} — {skill.description}{loaded}")

        return "\n".join(lines)
