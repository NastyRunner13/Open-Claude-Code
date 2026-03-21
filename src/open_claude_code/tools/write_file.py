"""Write file tool — create or overwrite files."""

import os

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


async def write_file(file_path: str, content: str) -> ToolResult:
    """Write content to a file, creating parent directories as needed."""
    try:
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except (PermissionError, OSError) as e:
        return ToolResult.fail(str(e), file_path=file_path)

    return ToolResult.ok(
        f"Successfully wrote {len(content)} characters to {file_path}",
        file_path=file_path,
        bytes_written=len(content),
    )
