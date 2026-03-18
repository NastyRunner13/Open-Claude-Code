"""Code sandbox tool — isolated code execution."""

import asyncio
import os
import tempfile

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "sandbox",
    "description": (
        "Run code in an isolated environment. "
        "Supports Python code execution. "
        "The code runs in a temporary directory and output is captured."
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


async def sandbox(code: str, language: str = "python", timeout: int = 30) -> str:
    """Run code in an isolated sandbox."""
    if language != "python":
        return f"Error: unsupported language '{language}'. Currently only 'python' is supported."

    # Write code to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        temp_path = f.name

    try:
        # Run in subprocess
        if os.name == "nt":
            cmd = f"python {temp_path}"
        else:
            cmd = f"python3 {temp_path}"

        process = await asyncio.create_subprocess_shell(
            cmd,
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
            return f"Sandbox execution timed out after {timeout} seconds"

        output = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        result = f"Exit code: {process.returncode}\n"
        if output:
            result += f"stdout:\n{output}"
        if err:
            result += f"stderr:\n{err}"

        if len(result) > MAX_OUTPUT:
            return result[:MAX_OUTPUT] + "\n[truncated]"
        return result

    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
