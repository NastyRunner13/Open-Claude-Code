"""Code sandbox tool — isolated code execution."""

import asyncio
import os
import sys
import tempfile

from open_claude_code.tools.context import (
    ToolContext,
    kill_process_tree,
    subprocess_isolation_kwargs,
    unbound_result,
)
from open_claude_code.tools.result import ToolResult

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "sandbox",
    "description": (
        "Run Python in a subprocess of this process. This is NOT a filesystem or "
        "network jail: the interpreter inherits the environment and can read/write "
        "the same files this agent can. Timeout is the only isolation. "
        "Prefer run_shell for workspace commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The code to execute.",
            },
            "language": {
                "type": "string",
                "description": "The programming language. Currently supports 'python'.",
                "default": "python",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Defaults to 30.",
                "default": 30,
            },
        },
        "required": ["code"],
    },
}


async def sandbox(
    code: str,
    language: str = "python",
    timeout: int = 30,
    _context: ToolContext | None = None,
) -> ToolResult:
    """Run Python in a subprocess. Timeout is the only isolation."""
    if _context is None:
        return unbound_result("sandbox")
    max_output = _context.max_output
    if language != "python":
        return ToolResult.fail(
            f"unsupported language '{language}'. Currently only 'python' is supported.",
            language=language,
        )

    # Write code to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Run in subprocess
        cmd = f'"{sys.executable}" "{temp_path}"'

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **subprocess_isolation_kwargs(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            await kill_process_tree(process)
            await process.communicate()
            return ToolResult.fail(
                f"Sandbox execution timed out after {timeout} seconds",
                language=language,
                exit_code=-1,
            )

        output = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        exit_code = process.returncode or 0

        result_text = f"Exit code: {exit_code}\n"
        if output:
            result_text += f"stdout:\n{output}"
        if err:
            result_text += f"stderr:\n{err}"

        truncated = len(result_text) > max_output
        if truncated:
            result_text = result_text[:max_output] + "\n[truncated]"

        return ToolResult(
            success=exit_code == 0,
            data=result_text,
            error=err.strip() if exit_code != 0 else None,
            metadata={"language": language, "exit_code": exit_code, "truncated": truncated},
        )

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
