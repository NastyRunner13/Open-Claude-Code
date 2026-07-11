"""Find files tool — glob-based search."""

import glob
import os

from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.result import ToolResult

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "find_files",
    "description": (
        "Find files matching a glob pattern. "
        "Supports recursive patterns like '**/*.py'. "
        "Returns matching file paths, one per line."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py', '*.js', 'src/**/*.ts').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to current directory.",
                "default": ".",
            },
        },
        "required": ["pattern"],
    },
}


async def find_files(
    pattern: str,
    path: str = ".",
    _context: ToolContext | None = None,
) -> ToolResult:
    """Find files matching a glob pattern."""
    target_path = path
    max_output = _context.max_output if _context else MAX_OUTPUT
    if _context:
        decision = _context.check_read_path(path)
        if not decision.allowed:
            await _context.emit_denied(
                "find_files", decision.reason, operation="read", path=decision.resolved_path
            )
            return ToolResult.fail(decision.reason, pattern=pattern, path=str(decision.resolved_path))
        target_path = str(decision.resolved_path)

    try:
        matches = glob.glob(os.path.join(target_path, pattern), recursive=True)
    except (PermissionError, OSError) as e:
        return ToolResult.fail(str(e), pattern=pattern, path=target_path)

    if _context:
        matches = [
            match for match in matches
            if _context.check_read_path(match).allowed
        ]

    if not matches:
        return ToolResult.ok(
            f"No files found matching pattern: {pattern}",
            pattern=pattern,
            match_count=0,
        )

    # Sort and limit results
    matches = sorted(matches)
    total = len(matches)
    truncated = total > 100
    if truncated:
        output = "\n".join(matches[:100]) + f"\n... and {total - 100} more files"
    else:
        output = "\n".join(matches)

    output_truncated = len(output) > max_output
    if output_truncated:
        output = output[:max_output] + "\n[truncated]"

    return ToolResult.ok(
        output,
        pattern=pattern,
        path=target_path,
        match_count=total,
        truncated=truncated or output_truncated,
    )
