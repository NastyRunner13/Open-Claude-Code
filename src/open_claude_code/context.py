"""Context management — conversation compaction and pruning.

Handles long conversations by:
1. Tracking token usage estimates
2. Compacting old messages (summarizing + pruning)
3. Preserving the most recent context and system instructions
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextStats:
    """Statistics about the current conversation context."""

    message_count: int
    estimated_tokens: int
    max_context_tokens: int
    utilization: float  # 0.0 to 1.0


def estimate_tokens(text: str) -> int:
    """Rough token estimate — ~4 characters per token for English."""
    return max(1, len(text) // 4)


def estimate_message_tokens(message: dict) -> int:
    """Estimate tokens in a single message."""
    content = message.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                if "text" in block:
                    total += estimate_tokens(block["text"])
                elif "thinking" in block:
                    total += estimate_tokens(block["thinking"])
                elif "content" in block:
                    total += estimate_tokens(str(block["content"]))
                # Tool use/result blocks
                if "input" in block:
                    total += estimate_tokens(str(block["input"]))
            elif isinstance(block, str):
                total += estimate_tokens(block)
        return total
    return 0


class ContextManager:
    """Manages conversation history to stay within context limits.

    Strategy:
      - Keep the first message (often contains important context)
      - Keep the most recent N messages
      - Summarize or prune middle messages when approaching limits
    """

    def __init__(
        self,
        max_context_tokens: int = 100000,
        compaction_threshold: float = 0.75,
        keep_recent: int = 20,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.compaction_threshold = compaction_threshold
        self.keep_recent = keep_recent

    def get_stats(self, history: list[dict]) -> ContextStats:
        """Get statistics about the current context."""
        total_tokens = sum(estimate_message_tokens(m) for m in history)
        utilization = total_tokens / self.max_context_tokens if self.max_context_tokens > 0 else 0

        return ContextStats(
            message_count=len(history),
            estimated_tokens=total_tokens,
            max_context_tokens=self.max_context_tokens,
            utilization=min(1.0, utilization),
        )

    def needs_compaction(self, history: list[dict]) -> bool:
        """Check if the history needs compaction."""
        stats = self.get_stats(history)
        return stats.utilization >= self.compaction_threshold

    def compact(self, history: list[dict]) -> list[dict]:
        """Compact the conversation history.

        Strategy:
          1. Keep the first 2 messages (initial context)
          2. Summarize middle messages into a compact form
          3. Keep the most recent `keep_recent` messages intact

        Returns a new list (does not modify the original).
        """
        if len(history) <= self.keep_recent + 2:
            return list(history)  # Nothing to compact

        # Messages to keep
        first_messages = history[:2]
        recent_messages = history[-self.keep_recent:]
        middle_messages = history[2:-self.keep_recent]

        if not middle_messages:
            return list(history)

        # Create a summary of the middle section
        summary_parts = []
        tool_calls_count = 0
        topics = set()

        for msg in middle_messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                # Extract first line as topic indicator
                first_line = content.strip().split("\n")[0][:100]
                if msg["role"] == "user":
                    topics.add(f"User: {first_line}")
                else:
                    topics.add(f"Assistant: {first_line}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_calls_count += 1
                        elif block.get("type") == "tool_result":
                            tool_calls_count += 1

        summary_text = (
            f"[Context compacted: {len(middle_messages)} messages removed, "
            f"{tool_calls_count} tool operations performed]\n\n"
            f"Topics covered:\n"
        )
        for topic in list(topics)[:10]:
            summary_text += f"  - {topic}\n"

        summary_message = {
            "role": "user",
            "content": summary_text,
        }

        return first_messages + [summary_message] + recent_messages

    def auto_compact(self, history: list[dict]) -> list[dict]:
        """Compact if needed, otherwise return as-is."""
        if self.needs_compaction(history):
            return self.compact(history)
        return history
