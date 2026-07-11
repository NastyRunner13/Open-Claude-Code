"""List directory tool."""

import os

from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.result import ToolResult

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "list_directory",
    "description": (
        "List the contents of a directory. "
        "Shows files and subdirectories with '/' suffix for directories."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The directory to list. Defaults to current directory.",
                "default": ".",
            },
        },
        "required": [],
    },
}


async def list_directory(
    path: str = ".",
    _context: ToolContext | None = None,
) -> ToolResult:
    """List entries in a directory."""
    target_path = path
    max_output = _context.max_output if _context else MAX_OUTPUT
    if _context:
        decision = _context.check_read_path(path)
        if not decision.allowed:
            await _context.emit_denied(
                "list_directory",
                decision.reason,
                operation="read",
                path=decision.resolved_path,
            )
            return ToolResult.fail(decision.reason, path=str(decision.resolved_path))
        target_path = str(decision.resolved_path)

    try:
        entries = sorted(os.listdir(target_path))
    except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
        return ToolResult.fail(str(e), path=target_path)

    result = []
    for entry in entries:
        full = os.path.join(target_path, entry)
        result.append(entry + "/" if os.path.isdir(full) else entry)

    output = "\n".join(result) if result else "(empty directory)"
    truncated = len(output) > max_output
    if truncated:
        output = output[:max_output] + "\n[truncated]"
    return ToolResult.ok(
        output,
        path=target_path,
        entry_count=len(entries),
        truncated=truncated,
    )
