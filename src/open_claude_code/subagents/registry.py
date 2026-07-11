"""Discovery and parsing for reusable project-local subagent definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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


def parse_agent_definition(path: Path) -> AgentDefinition:
    """Parse a markdown role file with optional YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
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
    if mode not in {"read-only", "workspace-write", "full-access"}:
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


class AgentRegistry:
    """Scans `.occ/agents` for named subagent role definitions."""

    def __init__(self, search_dirs: list[str | Path] | None = None) -> None:
        self.search_dirs = [Path(item).expanduser() for item in (search_dirs or [".occ/agents"])]
        self._definitions: dict[str, AgentDefinition] = {}
        self.rescan()

    def rescan(self) -> None:
        self._definitions.clear()
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
