"""YAML + env + CLI configuration system."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentConfig:
    """Agent configuration with sensible defaults."""

    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 16000
    max_tool_output: int = 10000

    mode: str = "agent"  # ask | plan | agent
    skip_approval: bool = False

    # Provider settings
    api_key: str | None = None
    base_url: str | None = None

    # Tools that auto-approve (no user prompt)
    auto_approve: list[str] = field(default_factory=lambda: [
        "read_file",
        "list_directory",
        "find_files",
        "grep_search",
        "web_search",
        "read_url",
    ])

    # Skill directories
    skills_dirs: list[str] = field(default_factory=lambda: [
        "~/.occ/skills",
        ".occ/skills",
    ])

    # Plugin directories
    plugins_dirs: list[str] = field(default_factory=lambda: [
        "~/.occ/plugins",
        ".occ/plugins",
    ])

    # MCP servers: list of {name, command, args, env}
    mcp_servers: list[dict] = field(default_factory=list)

    # Context management
    max_context_tokens: int = 100000
    context_compaction: bool = True

    # Prompt caching (Anthropic only — reduces cost up to 90%)
    prompt_caching: bool = True

    # Memory file search locations
    memory_dirs: list[str] = field(default_factory=lambda: ["."])


# Default config file search paths (project-local first, then global)
_DEFAULT_PATHS = [
    Path("occ.yml"),
    Path("occ.yaml"),
    Path(".occ/config.yml"),
    Path(".occ/config.yaml"),
]


def save_config(config: AgentConfig, path: str | Path | None = None) -> None:
    """Save configuration to YAML file."""
    config_path = Path(path) if path is not None else _DEFAULT_PATHS[0]
    
    if config_path.parent != Path(''):
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
    raw = {}
    if config_path.exists():
        try:
            raw = yaml.safe_load(config_path.read_text()) or {}
        except Exception:
            pass
            
    # Persist the dynamic configuration properties
    raw["mcp_servers"] = config.mcp_servers
    
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Load configuration from YAML file.

    Search order:
      1. Explicit path (if given)
      2. Project-local config files
      3. Defaults
    """
    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return _parse_config(config_path)

    for candidate in _DEFAULT_PATHS:
        if candidate.exists():
            return _parse_config(candidate)

    return AgentConfig()


def _parse_config(path: Path) -> AgentConfig:
    """Parse a YAML config file into an AgentConfig."""
    raw = yaml.safe_load(path.read_text()) or {}

    config = AgentConfig()

    if "model" in raw:
        config.model = raw["model"]
    if "max_tokens" in raw:
        config.max_tokens = raw["max_tokens"]
    if "max_tool_output" in raw:
        config.max_tool_output = raw["max_tool_output"]
    if "mode" in raw:
        config.mode = raw["mode"]
    if "skip_approval" in raw:
        config.skip_approval = raw["skip_approval"]
    if "auto_approve" in raw:
        config.auto_approve = raw["auto_approve"]
    if "skills_dirs" in raw:
        config.skills_dirs = raw["skills_dirs"]
    if "plugins_dirs" in raw:
        config.plugins_dirs = raw["plugins_dirs"]
    if "mcp_servers" in raw:
        config.mcp_servers = raw["mcp_servers"]
    if "max_context_tokens" in raw:
        config.max_context_tokens = raw["max_context_tokens"]
    if "context_compaction" in raw:
        config.context_compaction = raw["context_compaction"]
    if "prompt_caching" in raw:
        config.prompt_caching = raw["prompt_caching"]
    if "memory_dirs" in raw:
        config.memory_dirs = raw["memory_dirs"]

    return config
