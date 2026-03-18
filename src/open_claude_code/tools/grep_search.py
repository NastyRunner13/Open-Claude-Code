"""Grep search tool — search for patterns in files using ripgrep or fallback."""

import asyncio
import os
import re
import shutil

MAX_OUTPUT = 10000

SCHEMA = {
    "name": "grep_search",
    "description": (
        "Search for a pattern in files within a directory. "
        "Uses ripgrep (rg) if available for speed, otherwise falls back to Python grep. "
        "Returns matching lines with file names and line numbers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The search pattern (regex supported).",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to current directory.",
                "default": ".",
            },
            "include": {
                "type": "string",
                "description": "File glob to include (e.g. '*.py'). Optional.",
                "default": "",
            },
        },
        "required": ["pattern"],
    },
}


async def grep_search(pattern: str, path: str = ".", include: str = "") -> str:
    """Search for pattern in files."""
    # Try ripgrep first (much faster)
    rg_path = shutil.which("rg")
    if rg_path:
        return await _ripgrep_search(pattern, path, include)
    else:
        return await _python_grep(pattern, path, include)


async def _ripgrep_search(pattern: str, path: str, include: str) -> str:
    """Search using ripgrep."""
    cmd = ["rg", "--no-heading", "--line-number", "--color=never", "-S"]
    if include:
        cmd.extend(["--glob", include])
    cmd.extend([pattern, path])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        return "Error: search timed out after 30 seconds"
    except FileNotFoundError:
        return await _python_grep(pattern, path, include)

    output = stdout.decode("utf-8", errors="replace")
    if not output.strip():
        return f"No matches found for pattern: {pattern}"

    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[truncated]"
    return output


async def _python_grep(pattern: str, path: str, include: str) -> str:
    """Fallback grep using Python."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Error: invalid regex pattern — {e}"

    results = []
    target = os.path.abspath(path)

    if os.path.isfile(target):
        results.extend(_search_file(target, regex))
    elif os.path.isdir(target):
        for root, _dirs, files in os.walk(target):
            for fname in files:
                if include and not _glob_match(fname, include):
                    continue
                fpath = os.path.join(root, fname)
                results.extend(_search_file(fpath, regex))
                if len(results) > 200:
                    break
    else:
        return f"Error: {path} not found"

    if not results:
        return f"No matches found for pattern: {pattern}"

    output = "\n".join(results)
    if len(output) > MAX_OUTPUT:
        return output[:MAX_OUTPUT] + "\n[truncated]"
    return output


def _search_file(fpath: str, regex: re.Pattern) -> list[str]:
    """Search a single file for regex matches."""
    try:
        with open(fpath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except (PermissionError, IsADirectoryError, OSError):
        return []

    matches = []
    for i, line in enumerate(lines, 1):
        if regex.search(line):
            matches.append(f"{fpath}:{i}:{line.rstrip()}")
    return matches


def _glob_match(filename: str, pattern: str) -> bool:
    """Simple glob matching for file extensions."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)
