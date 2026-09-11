"""Discovery and parsing for reusable project-local subagent definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


EXPLORE_TOOLS = (
    "read_file",
    "list_directory",
    "find_files",
    "grep_search",
    "web_search",
    "read_url",
    "load_skill",
    "git_status",
    "git_diff",
    "git_log",
    "git_branch",
)

PLAN_TOOLS = EXPLORE_TOOLS + ("write_plan", "update_plan", "read_plan")

_EXPLORE_PROMPT = """\
You are an explore subagent. Investigate the codebase with read-only tools.
Do not edit files or run mutating shell commands. Use read_file, grep_search,
find_files, and git tools before answering. Return a concise report with
concrete file paths and findings. An empty report is valid only after you
have actually searched.
"""

_PLAN_PROMPT = """\
You are a plan subagent. Explore the codebase with read-only tools and produce
a step-by-step implementation plan. Do not edit files. Name the files that
will change. Use write_plan when the checklist tools are available.
"""

_GENERAL_PROMPT = """\
You are a general-purpose subagent. Complete the assigned task with the tools
you have. You cannot spawn further subagents. Report a concise result when
done. Read files before editing them.
"""


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    path: Path
    model: str = ""
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str = "read-only"
    max_turns: int = 25
    builtin: bool = False


@dataclass(frozen=True)
class Persona:
    name: str
    instructions: str
    description: str = ""
    path: Path = Path("<builtin>")


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    metadata: dict = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                import yaml
                loaded = yaml.safe_load(parts[1])
                metadata = loaded if isinstance(loaded, dict) else {}
            except Exception:
                metadata = {}
            body = parts[2].strip()
    return metadata, body


def parse_agent_definition(path: Path) -> AgentDefinition:
    """Parse a markdown role file with optional YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
    metadata, body = _parse_frontmatter(content)
    name = str(metadata.get("name") or path.stem)

    def list_value(key: str) -> tuple[str, ...]:
        value = metadata.get(key, [])
        if isinstance(value, str):
            return (value,)
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    try:
        max_turns = max(1, min(int(metadata.get("max_turns", 25)), 1000))
    except (TypeError, ValueError):
        max_turns = 25
    mode = str(metadata.get("permission_mode", "read-only"))
    if mode not in {"read-only", "workspace-write", "full-access", "inherit"}:
        mode = "read-only"
    return AgentDefinition(
        name=name,
        description=str(metadata.get("description", "")),
        system_prompt=body,
        path=path,
        model=str(metadata.get("model", "")),
        tools=list_value("tools"),
        disallowed_tools=list_value("disallowed_tools"),
        permission_mode=mode,
        max_turns=max_turns,
    )


def parse_persona(path: Path) -> Persona:
    """Parse a markdown persona overlay with optional YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
    metadata, body = _parse_frontmatter(content)
    name = str(metadata.get("name") or path.stem)
    extra = str(metadata.get("instructions", "")).strip()
    instructions = "\n\n".join(part for part in (extra, body) if part)
    return Persona(
        name=name,
        instructions=instructions,
        description=str(metadata.get("description", "")),
        path=path,
    )


def builtin_definitions() -> dict[str, AgentDefinition]:
    """Built-in roles that ship without `.occ/agents` files."""
    marker = Path("<builtin>")
    return {
        "explore": AgentDefinition(
            name="explore",
            description="Read-only research agent. Searches, reads, greps, and inspects git.",
            system_prompt=_EXPLORE_PROMPT.strip(),
            path=marker,
            tools=EXPLORE_TOOLS,
            permission_mode="read-only",
            builtin=True,
        ),
        "plan": AgentDefinition(
            name="plan",
            description="Read-only planner. Explores the tree and writes an implementation plan.",
            system_prompt=_PLAN_PROMPT.strip(),
            path=marker,
            tools=PLAN_TOOLS,
            permission_mode="read-only",
            builtin=True,
        ),
        "general-purpose": AgentDefinition(
            name="general-purpose",
            description="Full-capability child, clamped to the parent permission mode.",
            system_prompt=_GENERAL_PROMPT.strip(),
            path=marker,
            permission_mode="inherit",
            builtin=True,
        ),
    }


class AgentRegistry:
    """Built-in roles plus `.occ/agents` markdown definitions.

    Project files with the same name shadow the built-in of that name.
    """

    def __init__(self, search_dirs: list[str | Path] | None = None) -> None:
        self.search_dirs = [Path(item).expanduser() for item in (search_dirs or [".occ/agents"])]
        self._definitions: dict[str, AgentDefinition] = {}
        self.rescan()

    def rescan(self) -> None:
        self._definitions = builtin_definitions()
        for directory in self.search_dirs:
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                try:
                    definition = parse_agent_definition(path)
                    self._definitions[definition.name] = definition
                except OSError:
                    continue

    @property
    def definitions(self) -> dict[str, AgentDefinition]:
        return dict(self._definitions)

    def get(self, name: str) -> AgentDefinition | None:
        return self._definitions.get(name)


class PersonaRegistry:
    """Project-local persona overlays from `.occ/personas/*.md`."""

    def __init__(self, search_dirs: list[str | Path] | None = None) -> None:
        self.search_dirs = [Path(item).expanduser() for item in (search_dirs or [".occ/personas"])]
        self._personas: dict[str, Persona] = {}
        self.rescan()

    def rescan(self) -> None:
        self._personas.clear()
        for directory in self.search_dirs:
            if not directory.is_dir():
                continue
            for path in directory.glob("*.md"):
                try:
                    persona = parse_persona(path)
                    self._personas[persona.name] = persona
                except OSError:
                    continue

    @property
    def personas(self) -> dict[str, Persona]:
        return dict(self._personas)

    def get(self, name: str) -> Persona | None:
        return self._personas.get(name)
