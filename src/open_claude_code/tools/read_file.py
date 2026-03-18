"""Read file tool."""

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "read_file",
    "description": (
        "Read the contents of a file at the given path. "
        "Returns the file contents as a string. "
        "Use this to understand existing code before making changes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute or relative path to the file to read.",
            },
        },
        "required": ["file_path"],
    },
}


async def read_file(file_path: str) -> str:
    """Read a file and return its contents."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
        return f"Error: {e}"

    if len(content) > MAX_OUTPUT:
        return content[:MAX_OUTPUT] + "\n[truncated]"
    return content
