"""Shell command execution tool."""

import asyncio
import os

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


async def run_shell(command: str, timeout: int = 60) -> str:
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
        return f"Command timed out after {timeout} seconds"

    output = stdout.decode("utf-8", errors="replace")
    err_output = stderr.decode("utf-8", errors="replace")
    combined = output + err_output
    result = f"Exit code: {process.returncode}\n{combined}"

    if len(result) > MAX_OUTPUT:
        return result[:MAX_OUTPUT] + "\n[truncated]"
    return result
