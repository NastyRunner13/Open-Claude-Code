"""Spawn agent tool schema. Execution is handled directly by the agent loop."""

SCHEMA = {
    "name": "spawn_agent",
    "description": (
        "Spawn a sub-agent to handle a subtask independently. "
        "The sub-agent gets its own conversation history and auto-approves all tool calls. "
        "Use this for tasks that can run in parallel, like analyzing multiple files or modules."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear description of the subtask for the sub-agent.",
            },
        },
        "required": ["task"],
    },
}
