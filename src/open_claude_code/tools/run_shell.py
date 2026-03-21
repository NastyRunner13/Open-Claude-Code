"""Shell command execution tool."""

import asyncio
import os

from open_claude_code.tools.result import ToolResult

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "run_shell",
    "description": (
        "Execute a shell command and return the output. "
        "The command runs in the current working directory. "
        "Use this for running tests, installing packages, git operations, etc."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Defaults to 60.",
                "default": 60,
            },
        },
        "required": ["command"],
    },
}


async def run_shell(command: str, timeout: int = 60) -> ToolResult:
    """Run a shell command and return combined stdout/stderr."""
    # Use cmd.exe on Windows, bash/sh on Unix
    if os.name == "nt":
        shell_cmd = f"cmd /c {command}"
    else:
        shell_cmd = command

    process = await asyncio.create_subprocess_shell(
        shell_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return ToolResult.fail(
            f"Command timed out after {timeout} seconds",
            command=command,
            exit_code=-1,
        )

    output = stdout.decode("utf-8", errors="replace")
    err_output = stderr.decode("utf-8", errors="replace")
    combined = output + err_output
    exit_code = process.returncode or 0

    result_text = f"Exit code: {exit_code}\n{combined}"
    truncated = len(result_text) > MAX_OUTPUT
    if truncated:
        result_text = result_text[:MAX_OUTPUT] + "\n[truncated]"

    return ToolResult(
        success=exit_code == 0,
        data=result_text,
        error=err_output.strip() if exit_code != 0 else None,
        metadata={"command": command, "exit_code": exit_code, "truncated": truncated},
    )
