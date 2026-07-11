"""Tool registry — collects and exposes all tools to the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from open_claude_code.tools.edit_file import SCHEMA as EDIT_FILE_SCHEMA
from open_claude_code.tools.edit_file import edit_file
from open_claude_code.tools.multi_edit import SCHEMA as MULTI_EDIT_SCHEMA
from open_claude_code.tools.multi_edit import multi_edit
from open_claude_code.tools.apply_patch import SCHEMA as APPLY_PATCH_SCHEMA
from open_claude_code.tools.apply_patch import apply_patch
from open_claude_code.tools.undo_edit import SCHEMA as UNDO_EDIT_SCHEMA
from open_claude_code.tools.undo_edit import undo_edit
from open_claude_code.tools.git import (
    GIT_BRANCH_SCHEMA,
    GIT_DIFF_SCHEMA,
    GIT_LOG_SCHEMA,
    GIT_STATUS_SCHEMA,
    git_branch,
    git_diff,
    git_log,
    git_status,
)
from open_claude_code.tools.find_files import SCHEMA as FIND_FILES_SCHEMA
from open_claude_code.tools.find_files import find_files
from open_claude_code.tools.grep_search import SCHEMA as GREP_SEARCH_SCHEMA
from open_claude_code.tools.grep_search import grep_search
from open_claude_code.tools.list_directory import SCHEMA as LIST_DIRECTORY_SCHEMA
from open_claude_code.tools.list_directory import list_directory
from open_claude_code.tools.load_skill import SCHEMA as LOAD_SKILL_SCHEMA
from open_claude_code.tools.load_skill import load_skill
from open_claude_code.tools.read_file import SCHEMA as READ_FILE_SCHEMA
from open_claude_code.tools.read_file import read_file
from open_claude_code.tools.read_url import SCHEMA as READ_URL_SCHEMA
from open_claude_code.tools.read_url import read_url
from open_claude_code.tools.run_shell import SCHEMA as RUN_SHELL_SCHEMA
from open_claude_code.tools.run_shell import run_shell
from open_claude_code.tools.sandbox import SCHEMA as SANDBOX_SCHEMA
from open_claude_code.tools.sandbox import sandbox
from open_claude_code.tools.spawn_agent import SCHEMA as SPAWN_AGENT_SCHEMA
from open_claude_code.tools.web_search import SCHEMA as WEB_SEARCH_SCHEMA
from open_claude_code.tools.web_search import web_search
from open_claude_code.tools.write_file import SCHEMA as WRITE_FILE_SCHEMA
from open_claude_code.tools.write_file import write_file
from open_claude_code.tools.context import ToolContext

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig
    from open_claude_code.events import EventBus
    from open_claude_code.skills import SkillManager


def get_tools(
    skill_manager: "SkillManager | None" = None,
    config: "AgentConfig | None" = None,
    event_bus: "EventBus | None" = None,
    session_id: str | None = None,
) -> dict:
    """Return the full tool registry.

    Args:
        skill_manager: Optional SkillManager to inject into the load_skill tool.
        config: Optional AgentConfig used to bind runtime tool policy.
        event_bus: Optional EventBus used for policy-denied events.
    """
    tool_context = (
        ToolContext.from_config(config=config, event_bus=event_bus, session_id=session_id)
        if config or event_bus
        else None
    )

    # Create a bound load_skill function with the manager injected
    async def bound_load_skill(name: str) -> str:
        return await load_skill(name, _skill_manager=skill_manager)

    async def bound_read_file(file_path: str, offset: int = 0, limit: int = 0, line_numbers: bool = False):
        return await read_file(file_path, offset, limit, line_numbers, _context=tool_context)

    async def bound_write_file(file_path: str, content: str):
        return await write_file(file_path, content, _context=tool_context)

    async def bound_edit_file(file_path: str, old_string: str, new_string: str):
        return await edit_file(file_path, old_string, new_string, _context=tool_context)

    async def bound_multi_edit(file_path: str, edits: list[dict]):
        return await multi_edit(file_path, edits, _context=tool_context)

    async def bound_apply_patch(patch: str):
        return await apply_patch(patch, _context=tool_context)

    async def bound_undo_edit(file_path: str = "", snapshot_id: str = ""):
        return await undo_edit(file_path, snapshot_id, _context=tool_context)

    async def bound_git_status():
        return await git_status(_context=tool_context)

    async def bound_git_diff(staged: bool = False, base: str = "", path: str = ""):
        return await git_diff(staged, base, path, _context=tool_context)

    async def bound_git_log(limit: int = 10):
        return await git_log(limit, _context=tool_context)

    async def bound_git_branch():
        return await git_branch(_context=tool_context)

    async def bound_list_directory(path: str = "."):
        return await list_directory(path, _context=tool_context)

    async def bound_find_files(pattern: str, path: str = "."):
        return await find_files(pattern, path, _context=tool_context)

    async def bound_grep_search(pattern: str, path: str = ".", include: str = ""):
        return await grep_search(pattern, path, include, _context=tool_context)

    async def bound_run_shell(command: str, timeout: int = 60, cwd: str = ""):
        return await run_shell(command, timeout, cwd, _context=tool_context)

    async def bound_web_search(query: str, max_results: int = 5):
        return await web_search(query, max_results, _context=tool_context)

    async def bound_read_url(url: str):
        return await read_url(url, _context=tool_context)

    async def bound_sandbox(code: str, language: str = "python", timeout: int = 30):
        return await sandbox(code, language, timeout, _context=tool_context)

    tools = {
        "read_file": {
            "function": bound_read_file,
            "schema": READ_FILE_SCHEMA,
        },
        "write_file": {
            "function": bound_write_file,
            "schema": WRITE_FILE_SCHEMA,
        },
        "edit_file": {
            "function": bound_edit_file,
            "schema": EDIT_FILE_SCHEMA,
        },
        "multi_edit": {
            "function": bound_multi_edit,
            "schema": MULTI_EDIT_SCHEMA,
        },
        "apply_patch": {
            "function": bound_apply_patch,
            "schema": APPLY_PATCH_SCHEMA,
        },
        "undo_edit": {
            "function": bound_undo_edit,
            "schema": UNDO_EDIT_SCHEMA,
        },
        "git_status": {"function": bound_git_status, "schema": GIT_STATUS_SCHEMA},
        "git_diff": {"function": bound_git_diff, "schema": GIT_DIFF_SCHEMA},
        "git_log": {"function": bound_git_log, "schema": GIT_LOG_SCHEMA},
        "git_branch": {"function": bound_git_branch, "schema": GIT_BRANCH_SCHEMA},
        "list_directory": {
            "function": bound_list_directory,
            "schema": LIST_DIRECTORY_SCHEMA,
        },
        "find_files": {
            "function": bound_find_files,
            "schema": FIND_FILES_SCHEMA,
        },
        "grep_search": {
            "function": bound_grep_search,
            "schema": GREP_SEARCH_SCHEMA,
        },
        "run_shell": {
            "function": bound_run_shell,
            "schema": RUN_SHELL_SCHEMA,
        },
        "web_search": {
            "function": bound_web_search,
            "schema": WEB_SEARCH_SCHEMA,
        },
        "read_url": {
            "function": bound_read_url,
            "schema": READ_URL_SCHEMA,
        },
        "sandbox": {
            "function": bound_sandbox,
            "schema": SANDBOX_SCHEMA,
        },
        "spawn_agent": {
            "function": None,  # Handled directly by the agent loop
            "schema": SPAWN_AGENT_SCHEMA,
        },
        "load_skill": {
            "function": bound_load_skill,
            "schema": LOAD_SKILL_SCHEMA,
        },
    }

    return tools
