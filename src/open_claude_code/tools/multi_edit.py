"""Atomic multi-replacement file edits."""

from __future__ import annotations

from typing import Any

from open_claude_code.tools.changes import result_with_diff, unified_diff
from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.result import ToolResult


SCHEMA = {
    "name": "multi_edit",
    "description": "Apply multiple exact, unique replacements to one file atomically. No change is written if any replacement fails.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to the file to edit."},
            "edits": {
                "type": "array",
                "description": "Exact replacements to apply in order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["old_string", "new_string"],
                },
            },
        },
        "required": ["file_path", "edits"],
    },
}


async def multi_edit(
    file_path: str,
    edits: list[dict[str, Any]],
    _context: ToolContext | None = None,
) -> ToolResult:
    """Apply exact replacements as one all-or-nothing change."""
    target_path = file_path
    if _context:
        decision = _context.check_write_path(file_path)
        if not decision.allowed:
            await _context.emit_denied("multi_edit", decision.reason, operation="write", path=decision.resolved_path)
            return ToolResult.fail(decision.reason, file_path=str(decision.resolved_path))
        target_path = str(decision.resolved_path)
    if not edits:
        return ToolResult.fail("edits cannot be empty", file_path=target_path)

    try:
        with open(target_path, encoding="utf-8") as handle:
            original = handle.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as exc:
        return ToolResult.fail(str(exc), file_path=target_path)

    updated = original
    for index, edit in enumerate(edits, start=1):
        old = edit.get("old_string")
        new = edit.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return ToolResult.fail(f"edit {index} requires string old_string and new_string", file_path=target_path)
        if not old:
            return ToolResult.fail(f"edit {index} old_string cannot be empty", file_path=target_path)
        first = updated.find(old)
        if first < 0:
            return ToolResult.fail(f"edit {index} old_string not found; no changes were written", file_path=target_path)
        if updated.find(old, first + 1) >= 0:
            return ToolResult.fail(f"edit {index} old_string is not unique; no changes were written", file_path=target_path)
        updated = updated[:first] + new + updated[first + len(old):]

    try:
        snapshot = _context.snapshots.create(target_path) if _context and _context.snapshots else None
        with open(target_path, "w", encoding="utf-8") as handle:
            handle.write(updated)
    except (PermissionError, OSError) as exc:
        return ToolResult.fail(str(exc), file_path=target_path)

    diff = unified_diff(original, updated, target_path, _context.max_output if _context else 10000)
    message = f"Successfully applied {len(edits)} edit(s) to {target_path}"
    return ToolResult.ok(
        result_with_diff(message, diff),
        file_path=target_path,
        edit_count=len(edits),
        diff=diff,
        snapshot_id=snapshot.snapshot_id if snapshot else None,
    )
