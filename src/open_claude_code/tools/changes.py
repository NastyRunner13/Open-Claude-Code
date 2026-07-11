"""Small utilities shared by file-changing tools."""

from __future__ import annotations

import difflib
from pathlib import Path


def unified_diff(before: str, after: str, file_path: str | Path, max_chars: int = 10000) -> str:
    """Return a bounded, conventional unified diff for a single file change."""
    path = str(file_path).replace("\\", "/")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if len(diff) > max_chars:
        return diff[:max_chars] + "\n[diff truncated]\n"
    return diff


def result_with_diff(message: str, diff: str) -> str:
    """Keep the usual success message while making reviewable evidence visible."""
    return f"{message}\n\nDiff:\n{diff}" if diff else message
