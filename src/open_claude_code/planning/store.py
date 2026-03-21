"""In-memory plan store — manages a persistent checklist for the agent.

The plan persists across turns within a single session, giving the agent
a structured way to track multi-step tasks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal


PlanStatus = Literal["pending", "in_progress", "done"]


@dataclass
class PlanItem:
    """A single item in the plan checklist."""

    id: str
    text: str
    status: PlanStatus = "pending"

    @property
    def icon(self) -> str:
        """Status icon for display."""
        return {"pending": "○", "in_progress": "◐", "done": "●"}[self.status]

    @property
    def checkbox(self) -> str:
        """Markdown checkbox for display."""
        return {"pending": "[ ]", "in_progress": "[/]", "done": "[x]"}[self.status]


class PlanStore:
    """Persistent plan state — survives across agent turns.

    Provides CRUD operations on a structured checklist.
    """

    def __init__(self) -> None:
        self.title: str = ""
        self.items: list[PlanItem] = []
        self._active: bool = False

    @property
    def is_active(self) -> bool:
        """Whether a plan currently exists."""
        return self._active and len(self.items) > 0

    @property
    def progress(self) -> tuple[int, int]:
        """Return (completed, total) counts."""
        done = sum(1 for item in self.items if item.status == "done")
        return done, len(self.items)

    @property
    def progress_str(self) -> str:
        """Human-readable progress string."""
        done, total = self.progress
        if total == 0:
            return "No plan"
        return f"{done}/{total} steps done"

    def write(self, title: str, steps: list[str]) -> str:
        """Create or overwrite the plan.

        Args:
            title: Plan title/description.
            steps: List of step descriptions.

        Returns:
            Confirmation message.
        """
        self.title = title
        self.items = [
            PlanItem(id=f"step_{i + 1}", text=step.strip())
            for i, step in enumerate(steps)
            if step.strip()
        ]
        self._active = True
        return f"Plan created: '{title}' with {len(self.items)} steps.\n\n{self.to_markdown()}"

    def update(
        self,
        item_id: str,
        status: PlanStatus | None = None,
        text: str | None = None,
    ) -> str:
        """Update an item's status or text.

        Args:
            item_id: The item ID (e.g., 'step_1').
            status: New status ('pending', 'in_progress', 'done').
            text: New text for the item.

        Returns:
            Confirmation or error message.
        """
        item = self._find_item(item_id)
        if item is None:
            return f"Error: Item '{item_id}' not found. Use read_plan to see available items."

        changes = []
        if status is not None:
            item.status = status
            changes.append(f"status → {status}")
        if text is not None:
            item.text = text
            changes.append("text updated")

        if not changes:
            return "No changes specified."

        return f"Updated {item_id}: {', '.join(changes)}.\n\n{self.to_markdown()}"

    def add(self, text: str, after_id: str | None = None) -> str:
        """Add a new item to the plan.

        Args:
            text: Description of the new step.
            after_id: Insert after this item. If None, appends to end.

        Returns:
            Confirmation message.
        """
        new_id = f"step_{len(self.items) + 1}_{uuid.uuid4().hex[:4]}"
        new_item = PlanItem(id=new_id, text=text.strip())

        if after_id is not None:
            idx = self._find_index(after_id)
            if idx is None:
                return f"Error: Item '{after_id}' not found."
            self.items.insert(idx + 1, new_item)
        else:
            self.items.append(new_item)

        return f"Added step '{new_id}': {text}\n\n{self.to_markdown()}"

    def remove(self, item_id: str) -> str:
        """Remove an item from the plan.

        Args:
            item_id: The item ID to remove.

        Returns:
            Confirmation or error message.
        """
        idx = self._find_index(item_id)
        if idx is None:
            return f"Error: Item '{item_id}' not found."

        removed = self.items.pop(idx)
        return f"Removed: {removed.text}\n\n{self.to_markdown()}"

    def to_markdown(self) -> str:
        """Render the plan as a markdown checklist."""
        if not self.is_active:
            return "_No active plan._"

        done, total = self.progress
        lines = [f"## {self.title}", f"_Progress: {done}/{total} steps_", ""]

        for item in self.items:
            status_label = ""
            if item.status == "in_progress":
                status_label = " ⟵ in progress"
            lines.append(f"- {item.checkbox} **{item.id}**: {item.text}{status_label}")

        return "\n".join(lines)

    def to_compact(self) -> str:
        """Compact single-line summary for the prompt bar."""
        if not self.is_active:
            return ""
        done, total = self.progress
        current = next((i for i in self.items if i.status == "in_progress"), None)
        if current:
            return f"[Plan: {done}/{total} | Now: {current.text[:40]}]"
        return f"[Plan: {done}/{total}]"

    def _find_item(self, item_id: str) -> PlanItem | None:
        """Find an item by ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None

    def _find_index(self, item_id: str) -> int | None:
        """Find an item's index by ID."""
        for i, item in enumerate(self.items):
            if item.id == item_id:
                return i
        return None
