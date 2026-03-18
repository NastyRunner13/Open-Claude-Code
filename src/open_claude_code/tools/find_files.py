"""Find files tool — glob-based search."""

import glob
import os

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


async def find_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    try:
        matches = glob.glob(os.path.join(path, pattern), recursive=True)
    except (PermissionError, OSError) as e:
        return f"Error: {e}"

    if not matches:
        return f"No files found matching pattern: {pattern}"

    # Sort and limit results
    matches = sorted(matches)
    if len(matches) > 100:
        return "\n".join(matches[:100]) + f"\n... and {len(matches) - 100} more files"
    return "\n".join(matches)
