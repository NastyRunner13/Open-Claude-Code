"""List directory tool."""

import os

from open_claude_code.tools.result import ToolResult

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


async def list_directory(path: str = ".") -> ToolResult:
    """List entries in a directory."""
    try:
        entries = sorted(os.listdir(path))
    except (FileNotFoundError, PermissionError, NotADirectoryError) as e:
        return ToolResult.fail(str(e), path=path)

    result = []
    for entry in entries:
        full = os.path.join(path, entry)
        result.append(entry + "/" if os.path.isdir(full) else entry)

    output = "\n".join(result) if result else "(empty directory)"
    return ToolResult.ok(output, path=path, entry_count=len(entries))
