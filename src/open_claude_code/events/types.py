"""Event types for the agent lifecycle."""

from dataclasses import dataclass, field


@dataclass
class Thinking:
    """Emitted when the model produces a thinking/reasoning trace."""
    text: str


@dataclass
class PreToolUse:
    """Emitted before a tool is executed. Approval gate — listeners return True/False."""
    tool_name: str
    tool_params: dict
    requires_approval: bool = True


@dataclass
class PostToolUse:
    """Emitted after a tool has executed with its result."""
    tool_name: str
    result: str
    tool_use_id: str = ""


@dataclass
class Stop:
    """Emitted when the agent produces a final text response."""
    text: str


@dataclass
class SubagentStart:
    """Emitted when a sub-agent begins its task."""
    task: str


@dataclass
class SubagentStop:
    """Emitted when a sub-agent completes its task."""
    task: str
    result: str


@dataclass
class ModeChange:
    """Emitted when the interaction mode changes."""
    old_mode: str
    new_mode: str


@dataclass
class AgentStart:
    """Emitted when the agent begins processing a user request."""
    task: str
    mode: str


@dataclass
class Error:
    """Emitted when an error occurs."""
    message: str
    recoverable: bool = True
