"""Undo the latest reversible edit for a file or restore a named snapshot."""

from __future__ import annotations

from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.result import ToolResult


SCHEMA = {
    "name": "undo_edit",
    "description": "Restore a file from its latest OCC snapshot, or restore an explicit snapshot ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "File whose latest OCC edit should be undone."},
            "snapshot_id": {"type": "string", "description": "Explicit snapshot ID to restore."},
        },
    },
}


async def undo_edit(
    file_path: str = "",
    snapshot_id: str = "",
    _context: ToolContext | None = None,
) -> ToolResult:
    """Restore a before-change snapshot. Exactly one selector is required."""
    if _context is None or _context.snapshots is None:
        return ToolResult.fail("undo requires a runtime ToolContext with snapshots enabled")
    if bool(file_path) == bool(snapshot_id):
        return ToolResult.fail("provide exactly one of file_path or snapshot_id")

    if file_path:
        decision = _context.check_write_path(file_path)
        if not decision.allowed:
            await _context.emit_denied("undo_edit", decision.reason, operation="write", path=decision.resolved_path)
            return ToolResult.fail(decision.reason, file_path=str(decision.resolved_path))
        snapshot = _context.snapshots.latest_for(decision.resolved_path)
        if snapshot is None:
            return ToolResult.fail(f"no OCC snapshot found for {decision.resolved_path}")
        snapshot_id = snapshot.snapshot_id

    try:
        snapshot = _context.snapshots.restore(snapshot_id)
    except (KeyError, OSError) as exc:
        return ToolResult.fail(str(exc), snapshot_id=snapshot_id)

    return ToolResult.ok(
        f"Restored {snapshot.file_path} from snapshot {snapshot.snapshot_id}",
        file_path=str(snapshot.file_path),
        snapshot_id=snapshot.snapshot_id,
    )
