"""Load-skill tool — allows the LLM to load skills at runtime."""

SCHEMA = {
    "name": "load_skill",
    "description": (
        "Load a skill by name or path. Skills extend your capabilities with "
        "specialized instructions. Use list_skills() first to see available skills."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill to load, or a path to a skill directory.",
            },
        },
        "required": ["name"],
    },
}


async def load_skill(name: str, _skill_manager=None) -> str:
    """Load a skill by name. The _skill_manager is injected at tool registration time."""
    if _skill_manager is None:
        return "Error: Skill system not initialized."

    skill = _skill_manager.load(name)
    if skill is None:
        available = list(_skill_manager.available.keys())
        if available:
            return (
                f"Skill '{name}' not found. Available skills: {', '.join(available)}"
            )
        return (
            f"Skill '{name}' not found. No skills are currently available. "
            "Skills should be placed in ~/.occ/skills/ or .occ/skills/"
        )

    return (
        f"Skill '{skill.name}' loaded successfully.\n\n"
        f"Description: {skill.description}\n\n"
        f"Instructions have been added to your system prompt. "
        f"Follow the loaded skill's instructions for future tool calls."
    )
