"""Context management — LLM-powered conversation compaction.

Handles long conversations by:
1. Tracking token usage estimates
2. Using an LLM call to summarize pruned messages (replaces naive extraction)
3. Preserving the most recent context and system instructions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_claude_code.providers.base import Provider


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


def _extract_text_from_messages(messages: list[dict]) -> str:
    """Extract a text representation from a list of messages for summarization."""
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str):
            if content.strip():
                parts.append(f"[{role}]: {content[:500]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        parts.append(f"[{role}]: {block['text'][:500]}")
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool_call]: {block.get('name', '?')}({str(block.get('input', ''))[:200]})")
                    elif block.get("type") == "tool_result":
                        result_text = str(block.get("content", ""))[:200]
                        parts.append(f"[tool_result]: {result_text}")

    return "\n".join(parts)


def _naive_summary(middle_messages: list[dict]) -> str:
    """Fallback summarization when no LLM provider is available."""
    tool_calls_count = 0
    topics = set()

    for msg in middle_messages:
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
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

    summary = (
        f"[Context compacted: {len(middle_messages)} messages removed, "
        f"{tool_calls_count} tool operations performed]\n\n"
        f"Topics covered:\n"
    )
    for topic in list(topics)[:10]:
        summary += f"  - {topic}\n"

    return summary


class ContextManager:
    """Manages conversation history to stay within context limits.

    Strategy:
      - Keep the first message (often contains important context)
      - Keep the most recent N messages
      - Use an LLM to summarize pruned middle messages
      - Falls back to naive topic extraction if no provider available
    """

    def __init__(
        self,
        max_context_tokens: int = 100000,
        compaction_threshold: float = 0.75,
        keep_recent: int = 20,
        provider: "Provider | None" = None,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.compaction_threshold = compaction_threshold
        self.keep_recent = keep_recent
        self._provider = provider

    @property
    def provider(self) -> "Provider | None":
        return self._provider

    @provider.setter
    def provider(self, value: "Provider | None") -> None:
        self._provider = value

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

    async def compact(self, history: list[dict]) -> list[dict]:
        """Compact the conversation history using LLM summarization.

        Strategy:
          1. Keep the first 2 messages (initial context)
          2. Summarize middle messages using an LLM call
          3. Keep the most recent `keep_recent` messages intact

        Falls back to naive summarization if no provider is available.
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

        # Try LLM-powered summarization
        if self._provider:
            try:
                summary_text = await self._llm_summarize(middle_messages)
            except Exception:
                summary_text = _naive_summary(middle_messages)
        else:
            summary_text = _naive_summary(middle_messages)

        summary_message = {
            "role": "user",
            "content": summary_text,
        }

        return first_messages + [summary_message] + recent_messages

    async def _llm_summarize(self, messages: list[dict]) -> str:
        """Use an LLM to create an intelligent summary of pruned messages."""
        assert self._provider is not None

        # Build the text to summarize
        text = _extract_text_from_messages(messages)

        # Truncate to avoid excessive cost for summarization
        max_chars = 12000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[remaining messages truncated for summarization]"

        summarize_prompt = (
            "You are summarizing a section of a conversation between a user and an AI coding agent. "
            "This summary replaces the original messages in the conversation history to save context space.\n\n"
            "Create a concise summary that preserves:\n"
            "1. Key decisions and conclusions reached\n"
            "2. Important technical details (file paths, function names, error messages)\n"
            "3. What tools were used and their significant results\n"
            "4. Any outstanding questions or unresolved issues\n\n"
            "Format as a structured summary. Be concise but thorough."
        )

        summarize_messages = [
            {
                "role": "user",
                "content": (
                    f"Summarize this conversation segment ({len(messages)} messages):\n\n{text}"
                ),
            }
        ]

        response = await self._provider.send(
            messages=summarize_messages,
            tools=[],
            system_prompt=summarize_prompt,
        )

        # Extract text from response
        from open_claude_code.providers.base import TextBlock
        summary_parts = []
        for block in response.content:
            if isinstance(block, TextBlock):
                summary_parts.append(block.text)

        summary = "\n".join(summary_parts)

        return (
            f"[Context compacted — LLM summary of {len(messages)} previous messages]\n\n"
            f"{summary}"
        )

    def auto_compact(self, history: list[dict]) -> list[dict]:
        """Synchronous compat — use auto_compact_async for LLM summarization."""
        if self.needs_compaction(history):
            # Sync fallback — use naive summary
            if len(history) <= self.keep_recent + 2:
                return list(history)

            first_messages = history[:2]
            recent_messages = history[-self.keep_recent:]
            middle_messages = history[2:-self.keep_recent]

            if not middle_messages:
                return list(history)

            summary_message = {
                "role": "user",
                "content": _naive_summary(middle_messages),
            }
            return first_messages + [summary_message] + recent_messages

        return history

    async def auto_compact_async(self, history: list[dict]) -> list[dict]:
        """Compact if needed, using LLM if available."""
        if self.needs_compaction(history):
            return await self.compact(history)
        return history
