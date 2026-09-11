"""Write file tool — create or overwrite files."""

import os
from pathlib import Path

from open_claude_code.tools.changes import result_with_diff, unified_diff
from open_claude_code.tools.context import ToolContext, unbound_result
from open_claude_code.tools.result import ToolResult

SCHEMA = {
    "name": "write_file",
    "description": (
        "Write content to a file, creating parent directories if needed. "
        "If the file already exists, it will be overwritten. "
        "Use this to create new files. For modifying existing files, prefer edit_file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    },
}


async def write_file(
    file_path: str,
    content: str,
    _context: ToolContext | None = None,
) -> ToolResult:
    """Write content to a file, creating parent directories as needed."""
    if _context is None:
        return unbound_result("write_file")
    target_path = file_path
    decision = _context.check_write_path(file_path)
    if not decision.allowed:
        await _context.emit_denied(
            "write_file", decision.reason, operation="write", path=decision.resolved_path
        )
        return ToolResult.fail(decision.reason, file_path=str(decision.resolved_path))
    target_path = str(decision.resolved_path)

    try:
        target = Path(target_path)
        previous_content = (
            target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        )
        snapshot = _context.snapshots.create(target) if _context.snapshots else None
        parent = os.path.dirname(target_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
    except (PermissionError, OSError) as e:
        return ToolResult.fail(str(e), file_path=target_path)

    diff = unified_diff(previous_content, content, target_path, _context.max_output)
    message = f"Successfully wrote {len(content)} characters to {target_path}"
    return ToolResult.ok(
        result_with_diff(message, diff),
        file_path=target_path,
        bytes_written=len(content),
        diff=diff,
        snapshot_id=snapshot.snapshot_id if snapshot else None,
    )
