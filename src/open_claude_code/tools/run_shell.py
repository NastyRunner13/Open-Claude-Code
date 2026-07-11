"""Shell command execution tool."""

import asyncio
import os

from open_claude_code.tools.context import ToolContext
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
            "cwd": {
                "type": "string",
                "description": "Working directory for the command. Defaults to the configured workspace cwd.",
                "default": "",
            },
        },
        "required": ["command"],
    },
}


async def run_shell(
    command: str,
    timeout: int = 60,
    cwd: str = "",
    _context: ToolContext | None = None,
) -> ToolResult:
    """Run a shell command and return combined stdout/stderr."""
    max_output = _context.max_output if _context else MAX_OUTPUT
    run_cwd = None
    classification = "unknown"

    if _context:
        shell_decision = _context.check_shell(command)
        classification = shell_decision.classification
        if not shell_decision.allowed:
            await _context.emit_denied(
                "run_shell",
                shell_decision.reason,
                operation=classification,
            )
            return ToolResult.fail(
                shell_decision.reason,
                command=command,
                classification=classification,
            )

        cwd_decision = _context.check_read_path(cwd or _context.cwd)
        if not cwd_decision.allowed:
            await _context.emit_denied(
                "run_shell",
                cwd_decision.reason,
                operation="cwd",
                path=cwd_decision.resolved_path,
            )
            return ToolResult.fail(
                cwd_decision.reason,
                command=command,
                cwd=str(cwd_decision.resolved_path),
                classification=classification,
            )
        run_cwd = str(cwd_decision.resolved_path)

    # Use cmd.exe on Windows, bash/sh on Unix
    if os.name == "nt":
        shell_cmd = f"cmd /c {command}"
    else:
        shell_cmd = command

    process = await asyncio.create_subprocess_shell(
        shell_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=run_cwd,
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
    truncated = len(result_text) > max_output
    if truncated:
        result_text = result_text[:max_output] + "\n[truncated]"

    return ToolResult(
        success=exit_code == 0,
        data=result_text,
        error=err_output.strip() if exit_code != 0 else None,
        metadata={
            "command": command,
            "cwd": run_cwd,
            "classification": classification,
            "exit_code": exit_code,
            "truncated": truncated,
        },
    )
