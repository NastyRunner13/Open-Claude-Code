"""Planning tools — write_plan, update_plan, read_plan.

These tools give the agent a persistent, structured checklist it can
reference and update across turns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from open_claude_code.planning.store import PlanStore


# ── Tool Schemas ──────────────────────────────────────────────────

WRITE_PLAN_SCHEMA = {
    "name": "write_plan",
    "description": (
        "Create or overwrite the current plan/todo list. Use this at the start of "
        "a complex task to break it into steps. Each step gets a unique ID you can "
        "reference later with update_plan."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title describing the overall task.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of step descriptions. Each becomes a checklist item.",
            },
        },
        "required": ["title", "steps"],
    },
}

UPDATE_PLAN_SCHEMA = {
    "name": "update_plan",
    "description": (
        "Update an item in the current plan. Use to mark steps as in_progress or done, "
        "change step text, add new steps, or remove steps. Call read_plan first if you "
        "need to see current item IDs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "ID of the plan item (e.g., 'step_1'). Required for update/remove.",
            },
            "action": {
                "type": "string",
                "enum": ["update", "add", "remove"],
                "description": "Action to perform. 'update' changes status/text, 'add' creates a new step, 'remove' deletes a step.",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done"],
                "description": "New status for the item (only for 'update' action).",
            },
            "text": {
                "type": "string",
                "description": "New text for 'update', or step description for 'add'.",
            },
            "after_id": {
                "type": "string",
                "description": "For 'add' action: insert after this item ID. Omit to append.",
            },
        },
        "required": ["action"],
    },
}

READ_PLAN_SCHEMA = {
    "name": "read_plan",
    "description": (
        "Read the current plan/todo list. Returns the full checklist with item IDs "
        "and statuses. Use this to check progress or get item IDs for update_plan."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


# ── Tool Functions ────────────────────────────────────────────────

def make_plan_tools(store: PlanStore) -> dict:
    """Create planning tool functions bound to a PlanStore instance.

    Args:
        store: The PlanStore to bind tools to.

    Returns:
        Dict of {name: {function, schema}} ready for the tool registry.
    """

    async def write_plan(title: str, steps: list[str]) -> str:
        """Create or overwrite the plan."""
        return store.write(title, steps)

    async def update_plan(
        action: str,
        item_id: str | None = None,
        status: str | None = None,
        text: str | None = None,
        after_id: str | None = None,
    ) -> str:
        """Update, add, or remove a plan item."""
        if action == "update":
            if item_id is None:
                return "Error: item_id is required for 'update' action."
            return store.update(item_id, status=status, text=text)
        elif action == "add":
            if text is None:
                return "Error: text is required for 'add' action."
            return store.add(text, after_id=after_id)
        elif action == "remove":
            if item_id is None:
                return "Error: item_id is required for 'remove' action."
            return store.remove(item_id)
        else:
            return f"Error: Unknown action '{action}'. Use 'update', 'add', or 'remove'."

    async def read_plan() -> str:
        """Read the current plan."""
        return store.to_markdown()

    return {
        "write_plan": {
            "function": write_plan,
            "schema": WRITE_PLAN_SCHEMA,
        },
        "update_plan": {
            "function": update_plan,
            "schema": UPDATE_PLAN_SCHEMA,
        },
        "read_plan": {
            "function": read_plan,
            "schema": READ_PLAN_SCHEMA,
        },
    }
