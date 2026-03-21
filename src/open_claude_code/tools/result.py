"""Structured result type for tool operations.

All tools return ToolResult instead of raw strings. The __str__ method
ensures backward-compatible string conversion so the agent loop and
existing tests work without changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Structured output from any tool operation.

    Attributes:
        success: Whether the operation succeeded.
        data: The primary output (content, message, etc.)
        error: Error message if success is False.
        metadata: Optional extra info (bytes written, exit code, etc.)
    """

    success: bool
    data: str | dict | list | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """String representation — backward-compatible with raw string returns.

        This is what gets sent back to the LLM as the tool_result content.
        """
        if not self.success:
            return f"Error: {self.error}" if self.error else "Error: unknown error"
        if self.data is None:
            return "OK"
        if isinstance(self.data, str):
            return self.data
        return str(self.data)

    @classmethod
    def ok(cls, data: str | dict | list | None = None, **metadata: Any) -> ToolResult:
        """Create a successful result."""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> ToolResult:
        """Create a failed result."""
        return cls(success=False, error=error, metadata=metadata)

    @property
    def is_error(self) -> bool:
        """Alias for not success."""
        return not self.success
