"""Sub-agent tool schemas. Execution lives on SubagentManager / the agent loop."""

PARENT_ONLY_TOOLS = frozenset(
    {
        "spawn_agent",
        "wait_agent",
        "kill_agent",
        "send_agent_message",
        "apply_agent_worktree",
        "run_workflow",
    }
)

PLAN_TOOL_NAMES = frozenset({"write_plan", "update_plan", "read_plan"})

SCHEMA = {
    "name": "spawn_agent",
    "description": (
        "Spawn a sub-agent to handle a subtask independently. "
        "Built-in types: explore (read-only research), plan (read-only planner), "
        "general-purpose (parent permission cap). Custom roles come from "
        ".occ/agents/<name>.md. Nested spawn_agent is stripped. "
        "background=true returns an id immediately; collect the result with wait_agent. "
        "isolation=worktree gives the child a private git worktree. "
        "resume_from continues a completed child's transcript. "
        "Output longer than 12k characters is truncated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "A clear description of the subtask for the sub-agent.",
            },
            "prompt": {
                "type": "string",
                "description": "Alias for task.",
            },
            "description": {
                "type": "string",
                "description": "Short 3-5 word label shown in the UI.",
            },
            "agent_type": {
                "type": "string",
                "description": (
                    "Role name: explore, plan, general-purpose, or a project-local "
                    "name from .occ/agents. Defaults to general-purpose."
                ),
            },
            "agent_name": {
                "type": "string",
                "description": "Alias for agent_type.",
            },
            "persona": {
                "type": "string",
                "description": "Optional overlay from .occ/personas/<name>.md.",
            },
            "permission_mode": {
                "type": "string",
                "enum": ["read-only", "workspace-write", "full-access"],
                "description": (
                    "Requested child permission mode. Clamped to the parent agent's "
                    "mode; the child cannot elevate. Default follows the role "
                    "(explore/plan: read-only; general-purpose: inherit parent)."
                ),
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum provider turns for this child. Defaults to the role definition or 25.",
            },
            "background": {
                "type": "boolean",
                "description": (
                    "If true, return an id immediately and keep running. "
                    "Collect the result with wait_agent. Default false (block until done)."
                ),
            },
            "isolation": {
                "type": "string",
                "enum": ["none", "worktree"],
                "description": (
                    "none shares the parent workspace (default). "
                    "worktree checks out a private git worktree under .occ/worktrees."
                ),
            },
            "resume_from": {
                "type": "string",
                "description": (
                    "Id of a completed subagent in this session. The new child "
                    "inherits that transcript and must use the same agent_type."
                ),
            },
            "cwd": {
                "type": "string",
                "description": (
                    "Working directory for the child. Mutually exclusive with "
                    "isolation=worktree. Ignored when resume_from is set."
                ),
            },
        },
        "required": ["task"],
    },
}

WAIT_AGENT_SCHEMA = {
    "name": "wait_agent",
    "description": (
        "Wait for one or more sub-agents to finish and return their results. "
        "Omit agent_ids to wait for every running child of this agent. "
        "timeout_ms=0 returns a snapshot without waiting. "
        "A positive timeout waits up to that many milliseconds."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Subagent ids to wait on. Empty waits for all running children.",
            },
            "agent_id": {
                "type": "string",
                "description": "Single-id alias for agent_ids.",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "0 = snapshot. Omit to wait until all complete. Capped at 3600000.",
            },
        },
    },
}

KILL_AGENT_SCHEMA = {
    "name": "kill_agent",
    "description": "Cancel a running sub-agent. Completed children are left as-is.",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Id returned by spawn_agent.",
            },
        },
        "required": ["agent_id"],
    },
}

SEND_AGENT_MESSAGE_SCHEMA = {
    "name": "send_agent_message",
    "description": (
        "Send a message to a running sub-agent. "
        "queue=false (steer) injects into the current turn at the next provider call. "
        "queue=true waits until the current run finishes, then starts a follow-up turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Id of a running sub-agent.",
            },
            "message": {
                "type": "string",
                "description": "Text delivered as a user message to the child.",
            },
            "queue": {
                "type": "boolean",
                "description": "If true, run as a follow-up turn after the current one. Default false (steer).",
            },
        },
        "required": ["agent_id", "message"],
    },
}

APPLY_AGENT_WORKTREE_SCHEMA = {
    "name": "apply_agent_worktree",
    "description": (
        "Copy files changed in a sub-agent's git worktree into the parent workspace. "
        "Does not merge git history. Denied paths stay denied by ToolContext."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Id of a sub-agent that used isolation=worktree.",
            },
        },
        "required": ["agent_id"],
    },
}

RUN_WORKFLOW_SCHEMA = {
    "name": "run_workflow",
    "description": (
        "Coordinate multiple sub-agents: each phase fans out jobs in parallel, "
        "waits for all of them, then starts the next phase. "
        "At most 8 jobs per phase and 32 jobs per workflow. "
        "Children still cannot spawn children."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "phases": {
                "type": "array",
                "description": "Ordered phases. Each phase is a parallel barrier.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Phase label."},
                        "jobs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "task": {"type": "string"},
                                    "description": {"type": "string"},
                                    "agent_type": {"type": "string"},
                                    "permission_mode": {"type": "string"},
                                    "isolation": {"type": "string"},
                                    "persona": {"type": "string"},
                                },
                                "required": ["task"],
                            },
                        },
                    },
                    "required": ["jobs"],
                },
            },
        },
        "required": ["phases"],
    },
}
