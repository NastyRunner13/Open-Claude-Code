"""Read-only Git inspection tools for coding and review workflows."""

from __future__ import annotations

import asyncio

from open_claude_code.tools.context import ToolContext, unbound_result
from open_claude_code.tools.result import ToolResult


def _schema(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties or {}, "required": required or []},
    }


GIT_STATUS_SCHEMA = _schema("git_status", "Show concise repository status without modifying the worktree.")
GIT_DIFF_SCHEMA = _schema(
    "git_diff",
    "Show a read-only Git diff. Set staged=true for the index, or provide a base ref.",
    {"staged": {"type": "boolean", "default": False}, "base": {"type": "string"}, "path": {"type": "string"}},
)
GIT_LOG_SCHEMA = _schema(
    "git_log",
    "Show recent commit history without modifying the repository.",
    {"limit": {"type": "integer", "default": 10}},
)
GIT_BRANCH_SCHEMA = _schema("git_branch", "Show the current branch and local branches without modifying the repository.")


async def _run_git(args: list[str], context: ToolContext | None, tool_name: str) -> ToolResult:
    if context is None:
        return unbound_result(tool_name)
    decision = context.check_read_path(context.cwd)
    if not decision.allowed:
        await context.emit_denied(tool_name, decision.reason, operation="read", path=decision.resolved_path)
        return ToolResult.fail(decision.reason)
    cwd = decision.resolved_path
    max_output = context.max_output
    try:
        process = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except (OSError, asyncio.TimeoutError) as exc:
        return ToolResult.fail(str(exc), command=["git", *args])
    output = (stdout + stderr).decode("utf-8", errors="replace")
    truncated = len(output) > max_output
    if truncated:
        output = output[:max_output] + "\n[truncated]"
    if process.returncode:
        return ToolResult.fail(output.strip() or f"git exited with {process.returncode}", exit_code=process.returncode)
    return ToolResult.ok(output or "(no output)", exit_code=0, truncated=truncated, cwd=str(cwd))


async def git_status(_context: ToolContext | None = None) -> ToolResult:
    return await _run_git(["status", "--short", "--branch"], _context, "git_status")


async def git_diff(
    staged: bool = False,
    base: str = "",
    path: str = "",
    _context: ToolContext | None = None,
) -> ToolResult:
    args = ["diff", "--no-ext-diff"]
    if staged:
        args.append("--staged")
    if base:
        args.append(base)
    if path:
        args.extend(["--", path])
    return await _run_git(args, _context, "git_diff")


async def git_log(limit: int = 10, _context: ToolContext | None = None) -> ToolResult:
    limit = max(1, min(int(limit), 100))
    return await _run_git(["log", f"--max-count={limit}", "--oneline", "--decorate"], _context, "git_log")


async def git_branch(_context: ToolContext | None = None) -> ToolResult:
    return await _run_git(["branch", "--show-current", "--all", "--no-color"], _context, "git_branch")
