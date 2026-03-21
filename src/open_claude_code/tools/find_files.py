"""Find files tool — glob-based search."""

import glob
import os

from open_claude_code.tools.result import ToolResult

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


async def find_files(pattern: str, path: str = ".") -> ToolResult:
    """Find files matching a glob pattern."""
    try:
        matches = glob.glob(os.path.join(path, pattern), recursive=True)
    except (PermissionError, OSError) as e:
        return ToolResult.fail(str(e), pattern=pattern, path=path)

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

    return ToolResult.ok(output, pattern=pattern, match_count=total, truncated=truncated)
