"""Minimal, validated unified-patch application for workspace files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from open_claude_code.tools.changes import unified_diff
from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.result import ToolResult


SCHEMA = {
    "name": "apply_patch",
    "description": "Apply a standard unified diff atomically after validating every hunk. Creates OCC snapshots for rollback.",
    "input_schema": {
        "type": "object",
        "properties": {"patch": {"type": "string", "description": "A unified diff containing one or more files."}},
        "required": ["patch"],
    },
}

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    path: str
    hunks: list[Hunk] = field(default_factory=list)


def _patch_path(value: str) -> str:
    path = value.split("\t", 1)[0].strip()
    if path in {"/dev/null", ""}:
        return ""
    return path[2:] if path.startswith(("a/", "b/")) else path


def _parse_patch(patch: str) -> list[FilePatch]:
    files: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None
    lines = patch.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("--- "):
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise ValueError("a '---' file header must be followed by '+++'")
            old_path = _patch_path(line[4:])
            new_path = _patch_path(lines[index + 1][4:])
            if not new_path:
                raise ValueError("deleting files through apply_patch is not supported; use a dedicated delete operation")
            if old_path and old_path != new_path:
                # Renames are intentionally not implicit: they are easy to review
                # separately and should not silently escape a writable root.
                raise ValueError("renames are not supported by apply_patch")
            current = FilePatch(path=new_path)
            files.append(current)
            hunk = None
            index += 2
            continue
        match = _HUNK_RE.match(line)
        if match:
            if current is None:
                raise ValueError("hunk found before a file header")
            hunk = Hunk(old_start=int(match.group(1)))
            current.hunks.append(hunk)
            index += 1
            continue
        if line.startswith("\\ No newline at end of file"):
            index += 1
            continue
        if hunk is not None and line[:1] in {" ", "+", "-"}:
            hunk.lines.append(line)
        index += 1
    if not files:
        raise ValueError("patch contains no unified-diff file headers")
    if any(not item.hunks for item in files):
        raise ValueError("each patched file must contain at least one hunk")
    return files


def _apply_hunks(original: str, patch: FilePatch) -> str:
    content = original.splitlines(keepends=True)
    offset = 0
    for hunk in patch.hunks:
        position = max(hunk.old_start - 1, 0) + offset
        if position > len(content):
            raise ValueError(f"hunk for {patch.path} starts beyond end of file")
        replacement: list[str] = []
        cursor = position
        for line in hunk.lines:
            kind, value = line[0], line[1:]
            if kind in {" ", "-"}:
                if cursor >= len(content) or content[cursor] != value:
                    raise ValueError(f"hunk context does not match {patch.path} at line {cursor + 1}")
                cursor += 1
            if kind in {" ", "+"}:
                replacement.append(value)
        content[position:cursor] = replacement
        offset += len(replacement) - (cursor - position)
    return "".join(content)


async def apply_patch(patch: str, _context: ToolContext | None = None) -> ToolResult:
    """Validate every patch hunk, then apply all files as one transaction."""
    if _context is None:
        return ToolResult.fail("apply_patch requires a runtime ToolContext")
    try:
        parsed = _parse_patch(patch)
    except ValueError as exc:
        return ToolResult.fail(str(exc))

    prepared: list[tuple[str, str, str]] = []
    for item in parsed:
        decision = _context.check_write_path(item.path)
        if not decision.allowed:
            await _context.emit_denied("apply_patch", decision.reason, operation="write", path=decision.resolved_path)
            return ToolResult.fail(decision.reason, file_path=str(decision.resolved_path))
        try:
            original = decision.resolved_path.read_text(encoding="utf-8") if decision.resolved_path.is_file() else ""
            updated = _apply_hunks(original, item)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return ToolResult.fail(str(exc), file_path=str(decision.resolved_path))
        prepared.append((str(decision.resolved_path), original, updated))

    snapshots: list[str] = []
    try:
        for path, _original, updated in prepared:
            snapshot = _context.snapshots.create(path) if _context.snapshots else None
            if snapshot:
                snapshots.append(snapshot.snapshot_id)
            target = _context.resolve_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
    except OSError as exc:
        # Best-effort rollback protects atomicity if a later file write fails.
        for snapshot_id in reversed(snapshots):
            try:
                assert _context.snapshots is not None
                _context.snapshots.restore(snapshot_id)
            except OSError:
                pass
        return ToolResult.fail(f"patch could not be applied and was rolled back: {exc}")

    diffs = [unified_diff(before, after, path, _context.max_output) for path, before, after in prepared]
    visible_diff = "\n".join(diff for diff in diffs if diff)
    message = f"Successfully applied patch to {len(prepared)} file(s)"
    return ToolResult.ok(
        f"{message}\n\nDiff:\n{visible_diff}" if visible_diff else message,
        file_count=len(prepared),
        diff=visible_diff,
        snapshot_ids=snapshots,
    )
