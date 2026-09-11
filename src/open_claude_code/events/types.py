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
class ToolDenied:
    """Emitted when runtime policy denies a tool before it can execute."""
    tool_name: str
    reason: str
    operation: str = ""
    path: str = ""


@dataclass
class TokenDelta:
    """A streamed content/reasoning fragment from the active provider."""
    text: str
    channel: str = "content"  # content | thinking


@dataclass
class ToolCallDelta:
    """A completed or partial streamed provider tool call."""
    tool_name: str
    tool_use_id: str = ""
    complete: bool = False


@dataclass
class UsageUpdated:
    """Normalized token usage and provider request metadata."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    request_id: str = ""
    finish_reason: str = ""
    latency_ms: float = 0.0
    model: str = ""


@dataclass
class ProviderFailure:
    """A structured provider failure suitable for logs and JSONL automation."""
    message: str
    transient: bool = False
    status_code: int | None = None


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
    agent_id: str = ""
    agent_type: str = ""
    background: bool = False
    isolation: str = "none"


@dataclass
class SubagentStop:
    """Emitted when a sub-agent completes its task."""
    task: str
    result: str
    agent_id: str = ""
    agent_type: str = ""
    status: str = "completed"
    worktree_path: str = ""


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


# ── Streaming events ───────────────────────────────────────────────

@dataclass
class StreamStart:
    """Emitted when the model begins streaming a response."""


@dataclass
class StreamTextDelta:
    """Emitted for each incremental text token from the stream."""
    text: str


@dataclass
class StreamThinkingDelta:
    """Emitted for each incremental thinking/reasoning token."""
    text: str


@dataclass
class StreamEnd:
    """Emitted when streaming is complete."""
    full_text: str
