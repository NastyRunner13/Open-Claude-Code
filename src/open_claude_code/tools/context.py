"""Runtime context and safety policy helpers for tool execution."""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from open_claude_code.events import ToolDenied
from open_claude_code.tools.snapshots import SnapshotStore

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig
    from open_claude_code.events import EventBus


READ_ONLY_COMMANDS = {
    "cat",
    "dir",
    "echo",
    "find",
    "git diff",
    "git log",
    "git show",
    "git status",
    "grep",
    "ls",
    "pwd",
    "rg",
    "type",
    "where",
    "which",
}

WRITE_COMMAND_RE = re.compile(
    r"(^|\b)(copy|cp|mkdir|move|mv|npm\s+install|pip\s+install|python\s+-m\s+pip|"
    r"ruff\s+check\s+--fix|touch|uv\s+add|uv\s+sync|write-file)(\b|$)|"
    r"(>>|>\s*[^&]|\bset-content\b|\bout-file\b)",
    re.IGNORECASE,
)

DESTRUCTIVE_COMMAND_RE = re.compile(
    r"(\brm\s+(-[^\s]*r[^\s]*f?|-f[^\s]*r)|\brmdir\b|\bdel\b|\berase\b|"
    r"\bformat\b|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[^\n]*f|"
    r"\bRemove-Item\b[^\n]*(\s-Recurse\b|\s-r\b))",
    re.IGNORECASE,
)


@dataclass
class PathDecision:
    """Result of a filesystem policy check."""

    allowed: bool
    resolved_path: Path
    reason: str = ""


@dataclass
class ShellDecision:
    """Result of a shell policy check."""

    allowed: bool
    classification: str
    reason: str = ""


@dataclass
class WebDecision:
    """Result of URL scheme/domain policy validation before any request."""

    allowed: bool
    host: str = ""
    reason: str = ""


@dataclass
class ToolContext:
    """Configuration and policy context passed to runtime-bound tools."""

    cwd: Path
    max_output: int
    workspace_roots: list[Path] = field(default_factory=list)
    writable_roots: list[Path] = field(default_factory=list)
    shell_policy: str = "workspace-write"
    snapshots_dir: Path | None = None
    session_id: str = "default"
    network_enabled: bool = True
    web_allowed_domains: list[str] = field(default_factory=list)
    web_blocked_domains: list[str] = field(default_factory=list)
    web_cache_dir: Path | None = None
    web_cache_ttl_seconds: int = 3600
    web_max_response_bytes: int = 1_000_000
    event_bus: "EventBus | None" = None
    _snapshot_store: SnapshotStore | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_config(
        cls,
        config: "AgentConfig | None" = None,
        event_bus: "EventBus | None" = None,
        cwd: str | Path | None = None,
        session_id: str | None = None,
    ) -> "ToolContext":
        base_cwd = Path(cwd or Path.cwd()).expanduser().resolve()
        workspace_values = config.workspace_roots if config else ["."]
        writable_values = config.writable_roots if config else ["."]
        return cls(
            cwd=base_cwd,
            max_output=config.max_tool_output if config else 10000,
            workspace_roots=[_resolve_root(p, base_cwd) for p in workspace_values],
            writable_roots=[_resolve_root(p, base_cwd) for p in writable_values],
            shell_policy=config.shell_policy if config else "workspace-write",
            snapshots_dir=(
                _resolve_root(config.snapshots_dir, base_cwd)
                if config and config.persist_snapshots
                else (_resolve_root(".occ/snapshots", base_cwd) if config is None else None)
            ),
            session_id=session_id or "default",
            network_enabled=config.network_enabled if config else True,
            web_allowed_domains=list(config.web_allowed_domains) if config else [],
            web_blocked_domains=list(config.web_blocked_domains) if config else [],
            web_cache_dir=_resolve_root(config.web_cache_dir if config else ".occ/cache/web", base_cwd),
            web_cache_ttl_seconds=config.web_cache_ttl_seconds if config else 3600,
            web_max_response_bytes=config.web_max_response_bytes if config else 1_000_000,
            event_bus=event_bus,
        )

    @property
    def snapshots(self) -> SnapshotStore | None:
        """The session-scoped store for reversible file edits, if configured."""
        if self.snapshots_dir is None:
            return None
        if self._snapshot_store is None:
            self._snapshot_store = SnapshotStore(self.snapshots_dir, self.session_id)
        return self._snapshot_store

    def resolve_path(self, path: str | Path) -> Path:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.cwd / target
        return target.resolve(strict=False)

    def check_read_path(self, path: str | Path) -> PathDecision:
        resolved = self.resolve_path(path)
        if _is_within_any(resolved, self.workspace_roots):
            return PathDecision(True, resolved)
        return PathDecision(
            False,
            resolved,
            f"read denied outside workspace roots: {resolved}",
        )

    def check_write_path(self, path: str | Path) -> PathDecision:
        resolved = self.resolve_path(path)
        if _is_within_any(resolved, self.writable_roots):
            return PathDecision(True, resolved)
        return PathDecision(
            False,
            resolved,
            f"write denied outside writable roots: {resolved}",
        )

    def check_shell(self, command: str) -> ShellDecision:
        classification = classify_shell_command(command)
        policy = self.shell_policy

        if policy not in {"read-only", "workspace-write", "full-access"}:
            return ShellDecision(
                False,
                classification,
                f"unknown shell policy '{policy}'",
            )

        if policy == "full-access":
            return ShellDecision(True, classification)

        if classification == "destructive":
            return ShellDecision(
                False,
                classification,
                "destructive shell command denied by policy",
            )

        if policy == "read-only" and classification != "read":
            return ShellDecision(
                False,
                classification,
                "non-read-only shell command denied by policy",
            )

        return ShellDecision(True, classification)

    def check_url(self, url: str) -> WebDecision:
        """Reject unsafe schemes, local hosts, and disallowed domains early."""
        from urllib.parse import urlparse

        if not self.network_enabled:
            return WebDecision(False, reason="network access is disabled by policy")
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return WebDecision(False, reason="only http and https URLs are allowed")
        if not parsed.hostname:
            return WebDecision(False, reason="URL must include a hostname")
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            return WebDecision(False, host=host, reason="localhost and local domains are blocked")
        if self.web_blocked_domains and _domain_matches(host, self.web_blocked_domains):
            return WebDecision(False, host=host, reason=f"domain '{host}' is blocked by policy")
        if self.web_allowed_domains and not _domain_matches(host, self.web_allowed_domains):
            return WebDecision(False, host=host, reason=f"domain '{host}' is not in the allowed-domain policy")
        return WebDecision(True, host=host)

    async def emit_denied(
        self,
        tool_name: str,
        reason: str,
        operation: str = "",
        path: str | Path = "",
    ) -> None:
        if self.event_bus is None:
            return
        await self.event_bus.emit(
            ToolDenied(
                tool_name=tool_name,
                reason=reason,
                operation=operation,
                path=str(path),
            )
        )


def classify_shell_command(command: str) -> str:
    """Classify a shell command for coarse policy enforcement."""
    stripped = command.strip()
    lowered = stripped.lower()
    if not stripped:
        return "read"
    if DESTRUCTIVE_COMMAND_RE.search(stripped):
        return "destructive"
    if WRITE_COMMAND_RE.search(stripped):
        return "write"

    first_segment = re.split(r"\s*(?:&&|\|\||;|\|)\s*", lowered, maxsplit=1)[0]
    for allowed in READ_ONLY_COMMANDS:
        if first_segment == allowed or first_segment.startswith(f"{allowed} "):
            return "read"

    return "unknown"


def _resolve_root(path: str | Path, cwd: Path) -> Path:
    root = Path(path).expanduser()
    if not root.is_absolute():
        root = cwd / root
    return root.resolve(strict=False)


def _is_within_any(path: Path, roots: list[Path]) -> bool:
    return any(_is_within(path, root) for root in roots)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _domain_matches(host: str, patterns: list[str]) -> bool:
    """Match exact domains, subdomains, and explicit shell-style patterns."""
    for pattern in patterns:
        normalized = pattern.strip().lower().lstrip(".")
        if not normalized:
            continue
        if fnmatchcase(host, normalized) or host == normalized or host.endswith(f".{normalized}"):
            return True
    return False
