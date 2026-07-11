"""Read file tool."""

from open_claude_code.tools.result import ToolResult
from open_claude_code.tools.context import ToolContext

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
            "offset": {
                "type": "integer",
                "description": "Zero-based line offset. Defaults to the start of the file.",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return. Defaults to output limit only.",
                "default": 0,
            },
            "line_numbers": {
                "type": "boolean",
                "description": "Prefix returned lines with one-based line numbers.",
                "default": False,
            },
        },
        "required": ["file_path"],
    },
}


async def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 0,
    line_numbers: bool = False,
    _context: ToolContext | None = None,
) -> ToolResult:
    """Read a file and return its contents."""
    target_path = file_path
    max_output = _context.max_output if _context else MAX_OUTPUT

    if _context:
        decision = _context.check_read_path(file_path)
        if not decision.allowed:
            await _context.emit_denied(
                "read_file", decision.reason, operation="read", path=decision.resolved_path
            )
            return ToolResult.fail(decision.reason, file_path=str(decision.resolved_path))
        target_path = str(decision.resolved_path)

    try:
        with open(target_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError, IsADirectoryError) as e:
        return ToolResult.fail(str(e), file_path=target_path)

    lines = content.splitlines(keepends=True)
    offset = max(0, int(offset))
    selected = lines[offset: offset + max(0, int(limit))] if limit else lines[offset:]
    if line_numbers:
        content = "".join(f"{number:>6}\t{line}" for number, line in enumerate(selected, offset + 1))
    else:
        content = "".join(selected)

    truncated = len(content) > max_output
    if truncated:
        content = content[:max_output] + "\n[truncated]"

    return ToolResult.ok(
        content,
        file_path=target_path,
        truncated=truncated,
        offset=offset,
        line_count=len(selected),
    )
