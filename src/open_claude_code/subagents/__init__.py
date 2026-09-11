"""Sub-agent system."""

from .manager import SubagentJob, SubagentManager
from .registry import (
    AgentDefinition,
    AgentRegistry,
    Persona,
    PersonaRegistry,
    builtin_definitions,
    parse_agent_definition,
    parse_persona,
)

__all__ = [
    "SubagentManager",
    "SubagentJob",
    "AgentDefinition",
    "AgentRegistry",
    "Persona",
    "PersonaRegistry",
    "builtin_definitions",
    "parse_agent_definition",
    "parse_persona",
]
