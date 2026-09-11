"""Agent-level capability policy applied before every tool dispatch.

``ToolContext`` protects the built-in tools themselves.  This policy is the
outer guard: it also covers MCP/plugin tools and gives child agents a strict,
least-privilege capability set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from open_claude_code.tools.context import classify_shell_command

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig


READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "list_directory",
        "find_files",
        "grep_search",
        "web_search",
        "read_url",
        "load_skill",
        "read_plan",
        "write_plan",
        "update_plan",
        "git_status",
        "git_diff",
        "git_log",
        "git_branch",
    }
)

_MODE_RANK = {
    "read-only": 0,
    "workspace-write": 1,
    "full-access": 2,
}


def clamp_permission_mode(requested: str, parent_mode: str, role_mode: str = "read-only") -> str:
    """Never let a child agent raise privilege above its parent."""
    parent = parent_mode if parent_mode in _MODE_RANK else "workspace-write"
    fallback = role_mode if role_mode in _MODE_RANK else "read-only"
    child = requested if requested in _MODE_RANK else fallback
    if _MODE_RANK[child] > _MODE_RANK[parent]:
        return parent
    return child


@dataclass(frozen=True)
class ToolPolicyDecision:
    """The allow/deny result for a requested tool call."""

    allowed: bool
    reason: str = ""
    operation: str = ""


@dataclass(frozen=True)
class ToolPolicy:
    """Capability policy for an agent instance.

    Modes deliberately describe *capabilities*, not just whether a confirmation
    prompt is shown.  A denied call cannot be overridden by ``skip_approval``.
    """

    mode: str = "workspace-write"
    disallowed_tools: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_config(cls, config: "AgentConfig | None" = None) -> "ToolPolicy":
        if config is None:
            return cls()
        return cls(
            mode=config.permission_mode,
            disallowed_tools=tuple(config.disallowed_tools),
        )

    def with_mode(self, mode: str) -> "ToolPolicy":
        """Return an equivalent policy with a narrower/different capability mode."""
        return ToolPolicy(mode=mode, disallowed_tools=self.disallowed_tools)

    def check_tool(self, tool_name: str, tool_params: dict | None = None) -> ToolPolicyDecision:
        """Decide whether a tool can be dispatched by this agent."""
        if self.mode not in {"read-only", "workspace-write", "full-access"}:
            return ToolPolicyDecision(
                False,
                f"unknown permission mode '{self.mode}'",
                operation="policy",
            )

        if any(fnmatchcase(tool_name, pattern) for pattern in self.disallowed_tools):
            return ToolPolicyDecision(
                False,
                f"tool '{tool_name}' is denied by policy",
                operation="tool",
            )

        if tool_name == "run_shell":
            return self._check_shell(str((tool_params or {}).get("command", "")))

        if self.mode == "read-only" and tool_name not in READ_ONLY_TOOLS:
            return ToolPolicyDecision(
                False,
                f"tool '{tool_name}' is unavailable in read-only mode",
                operation="tool",
            )

        return ToolPolicyDecision(True)

    def _check_shell(self, command: str) -> ToolPolicyDecision:
        classification = classify_shell_command(command)
        if self.mode == "full-access":
            return ToolPolicyDecision(True, operation=classification)
        if self.mode == "read-only" and classification != "read":
            return ToolPolicyDecision(
                False,
                "non-read-only shell command denied by read-only policy",
                operation=classification,
            )
        if self.mode == "workspace-write" and classification in {"unknown", "destructive"}:
            return ToolPolicyDecision(
                False,
                f"{classification} shell command denied by workspace-write policy",
                operation=classification,
            )
        if classification == "read" or self.mode == "workspace-write":
            return ToolPolicyDecision(True, operation=classification)
        return ToolPolicyDecision(
            False,
            f"tool 'run_shell' is unavailable in {self.mode} mode",
            operation=classification,
        )
