"""Event bus — simple async event dispatcher for the agent lifecycle."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from .types import PreToolUse


class EventBus:
    """Simple event dispatcher. Listeners are async callables registered by event type.

    The bus has two registration channels:
      - on(event_type, callback): general listeners (UI, logging, etc.)
      - on_approval(callback): a single approval handler for PreToolUse events

    emit() calls on() listeners only.
    emit_approval() calls on() listeners AND the approval handler.
    """

    def __init__(self) -> None:
        self._listeners: dict[type, list[Callable]] = defaultdict(list)
        self._approval_handler: Callable | None = None

    def on(self, event_type: type, callback: Callable) -> None:
        """Register an async callback for an event type."""
        self._listeners[event_type].append(callback)

    def on_approval(self, callback: Callable) -> None:
        """Register the approval handler for PreToolUse events."""
        self._approval_handler = callback

    async def emit(self, event: Any) -> None:
        """Emit an event to all registered listeners (not the approval handler)."""
        for callback in self._listeners[type(event)]:
            await callback(event)

    async def emit_approval(self, event: PreToolUse) -> bool:
        """Emit to regular listeners, then call the approval handler.

        Returns True if:
          - no approval handler is registered (default approve)
          - the tool doesn't require approval
          - the handler returns True
        """
        await self.emit(event)

        if not event.requires_approval:
            return True

        if self._approval_handler is None:
            return True

        result = await self._approval_handler(event)
        return result is not False
