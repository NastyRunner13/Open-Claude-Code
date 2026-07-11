"""Sub-agent system."""

from .manager import SubagentManager
from .registry import AgentDefinition, AgentRegistry, parse_agent_definition

__all__ = ["SubagentManager", "AgentDefinition", "AgentRegistry", "parse_agent_definition"]
