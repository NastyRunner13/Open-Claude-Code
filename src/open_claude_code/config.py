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

    # Capability policy applied before approval prompts.  A denied capability
    # cannot be enabled by --skip-approval or an auto-approve rule.
    permission_mode: str = "workspace-write"  # read-only | workspace-write | full-access
    disallowed_tools: list[str] = field(default_factory=list)

    # Provider settings
    api_key: str | None = None
    base_url: str | None = None
    # Ollama native context window. None means provider default (32768) or
    # OCC_OLLAMA_NUM_CTX. Ignored by other providers.
    num_ctx: int | None = None

    # Tools that auto-approve (no user prompt)
    auto_approve: list[str] = field(default_factory=lambda: [
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
        "wait_agent",
    ])

    # Filesystem safety. Paths are resolved relative to the process cwd.
    workspace_roots: list[str] = field(default_factory=lambda: ["."])
    writable_roots: list[str] = field(default_factory=lambda: ["."])

    # Shell policy: read-only | workspace-write | full-access
    shell_policy: str = "workspace-write"

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

    # Durable local session ledger. The snapshot written beside each transcript
    # deliberately redacts keys that look like credentials.
    persist_sessions: bool = True
    sessions_dir: str = ".occ/sessions"
    snapshots_dir: str = ".occ/snapshots"
    persist_snapshots: bool = True

    # Web safety. The default permits public HTTP(S) only and blocks private
    # network targets even when a model follows an untrusted link.
    network_enabled: bool = True
    web_allowed_domains: list[str] = field(default_factory=list)
    web_blocked_domains: list[str] = field(default_factory=list)
    web_cache_dir: str = ".occ/cache/web"
    web_cache_ttl_seconds: int = 3600
    web_max_response_bytes: int = 1_000_000

    # Transient provider errors (429/5xx) are retried with exponential backoff.
    provider_max_retries: int = 2
    provider_retry_base_delay: float = 0.5
    max_turns: int = 100
    agents_dirs: list[str] = field(default_factory=lambda: [".occ/agents"])
    personas_dirs: list[str] = field(default_factory=lambda: [".occ/personas", "~/.occ/personas"])
    hooks: dict[str, list[dict] | list[str]] = field(default_factory=dict)

    # Prompt caching (Anthropic only — reduces cost up to 90%)
    prompt_caching: bool = True

    # Memory file search locations
    memory_dirs: list[str] = field(default_factory=lambda: ["."])

    # Cost tracking. Prices are USD per million tokens. None budget means
    # unlimited. Unknown-model prices never masquerade as $0.00.
    max_budget_usd: float | None = None
    model_prices: dict[str, dict] = field(default_factory=dict)

    # User-level provider profile selected from ~/.occ/profiles.yml.
    # Set by load_config()/--profile; project occ.yml values still win for
    # model/base_url so a checked-in config is never silently overridden.
    active_profile: str | None = None


# Default config file search paths. These are project-local only; there is
# no user-global config file yet.
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


def find_config_path(path: str | Path | None = None) -> Path | None:
    """Return the YAML config file that load_config() would use, if any."""
    if path is not None:
        config_path = Path(path)
        return config_path if config_path.exists() else None
    for candidate in _DEFAULT_PATHS:
        if candidate.exists():
            return candidate
    return None


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Load configuration from YAML file.

    Search order:
      1. Explicit path (if given)
      2. Project-local config files (occ.yml, occ.yaml, .occ/config.yml)
      3. User-level provider profile (``~/.occ/profiles.yml`` active entry)
      4. Defaults

    A project file always wins over the user profile for the keys it sets,
    so saving a profile never rewrites a checked-in ``occ.yml`` by surprise.
    """
    base = AgentConfig()
    _apply_user_profile(base)

    if path is not None:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        _apply_file_to_config(base, config_path)
        return base

    for candidate in _DEFAULT_PATHS:
        if candidate.exists():
            _apply_file_to_config(base, candidate)
            return base

    return base


def _apply_user_profile(config: AgentConfig) -> None:
    """Overlay the active user profile, if any. Never raises, never reads keys."""
    try:
        from open_claude_code import profiles as _profiles
    except Exception:
        return
    try:
        name, settings = _profiles.get_active_profile()
    except Exception:
        return
    if not settings:
        return
    try:
        _profiles.apply_profile_to_config(config, settings)
    except Exception:
        return
    config.active_profile = name


def _apply_file_to_config(config: AgentConfig, path: Path) -> None:
    """Overlay one YAML file onto an existing config (project files win)."""
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must be a YAML mapping: {path}")
    _apply_raw(config, raw)


def _parse_config(path: Path) -> AgentConfig:
    """Parse a YAML config file into an AgentConfig."""
    config = AgentConfig()
    _apply_file_to_config(config, path)
    return config


def _apply_raw(config: AgentConfig, raw: dict) -> None:
    """Copy known YAML keys onto a config. Shared by load and parse paths."""

    if "model" in raw:
        config.model = raw["model"]
    if "base_url" in raw:
        config.base_url = raw["base_url"]
    if "num_ctx" in raw and raw["num_ctx"] is not None:
        config.num_ctx = int(raw["num_ctx"])
    if "max_tokens" in raw:
        config.max_tokens = raw["max_tokens"]
    if "max_tool_output" in raw:
        config.max_tool_output = raw["max_tool_output"]
    if "mode" in raw:
        config.mode = raw["mode"]
    if "skip_approval" in raw:
        config.skip_approval = raw["skip_approval"]
    if "permission_mode" in raw:
        config.permission_mode = raw["permission_mode"]
    if "disallowed_tools" in raw:
        config.disallowed_tools = raw["disallowed_tools"]
    if "auto_approve" in raw:
        config.auto_approve = raw["auto_approve"]
    if "workspace_roots" in raw:
        config.workspace_roots = raw["workspace_roots"]
    if "writable_roots" in raw:
        config.writable_roots = raw["writable_roots"]
    if "shell_policy" in raw:
        config.shell_policy = raw["shell_policy"]
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
    if "persist_sessions" in raw:
        config.persist_sessions = raw["persist_sessions"]
    if "sessions_dir" in raw:
        config.sessions_dir = raw["sessions_dir"]
    if "snapshots_dir" in raw:
        config.snapshots_dir = raw["snapshots_dir"]
    if "persist_snapshots" in raw:
        config.persist_snapshots = raw["persist_snapshots"]
    if "network_enabled" in raw:
        config.network_enabled = raw["network_enabled"]
    if "web_allowed_domains" in raw:
        config.web_allowed_domains = raw["web_allowed_domains"]
    if "web_blocked_domains" in raw:
        config.web_blocked_domains = raw["web_blocked_domains"]
    if "web_cache_dir" in raw:
        config.web_cache_dir = raw["web_cache_dir"]
    if "web_cache_ttl_seconds" in raw:
        config.web_cache_ttl_seconds = raw["web_cache_ttl_seconds"]
    if "web_max_response_bytes" in raw:
        config.web_max_response_bytes = raw["web_max_response_bytes"]
    if "provider_max_retries" in raw:
        config.provider_max_retries = raw["provider_max_retries"]
    if "provider_retry_base_delay" in raw:
        config.provider_retry_base_delay = raw["provider_retry_base_delay"]
    if "max_turns" in raw:
        config.max_turns = raw["max_turns"]
    if "agents_dirs" in raw:
        config.agents_dirs = raw["agents_dirs"]
    if "personas_dirs" in raw:
        config.personas_dirs = raw["personas_dirs"]
    if "hooks" in raw and isinstance(raw["hooks"], dict):
        config.hooks = raw["hooks"]
    if "prompt_caching" in raw:
        config.prompt_caching = raw["prompt_caching"]
    if "memory_dirs" in raw:
        config.memory_dirs = raw["memory_dirs"]
    if "max_budget_usd" in raw and raw["max_budget_usd"] is not None:
        config.max_budget_usd = float(raw["max_budget_usd"])
    if "model_prices" in raw and isinstance(raw["model_prices"], dict):
        config.model_prices = raw["model_prices"]
