"""Spawn agent tool schema. Execution is handled directly by the agent loop."""

SCHEMA = {
    "name": "spawn_agent",
    "description": (
        "Spawn a sub-agent to handle a subtask independently. "
        "The child gets its own conversation history and cannot raise privilege "
        "above this agent. Nested spawn_agent is stripped. Default mode is read-only. "
        "Output longer than 12k characters is truncated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear description of the subtask for the sub-agent.",
            },
            "agent_name": {
                "type": "string",
                "description": "Optional project-local role from .occ/agents/<name>.md.",
            },
            "permission_mode": {
                "type": "string",
                "enum": ["read-only", "workspace-write", "full-access"],
                "description": (
                    "Requested child permission mode. Clamped to the parent agent's "
                    "mode; the child cannot elevate. Default is read-only."
                ),
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum provider turns for this child. Defaults to the role definition or 25.",
            },
        },
        "required": ["task"],
    },
}
