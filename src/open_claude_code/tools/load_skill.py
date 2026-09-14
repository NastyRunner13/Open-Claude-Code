"""Load-skill tool — allows the LLM to load skills at runtime."""

from open_claude_code.tools.result import ToolResult

SCHEMA = {
    "name": "load_skill",
    "description": (
        "Load a skill by name or path. Skills extend your capabilities with "
        "specialized instructions. Available skills are listed in the system prompt."
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


async def load_skill(name: str, _skill_manager=None) -> ToolResult:
    """Load a skill by name. The _skill_manager is injected at tool registration time."""
    if _skill_manager is None:
        return ToolResult.fail("Skill system not initialized.", skill_name=name)

    metadata = _skill_manager.available.get(name)
    if metadata and metadata.disable_model_invocation:
        return ToolResult.fail(
            f"Skill '{name}' may only be loaded with the interactive /skill load command.",
            skill_name=name,
        )

    skill = _skill_manager.load(name)
    if skill is None:
        available = list(_skill_manager.available.keys())
        if available:
            return ToolResult.fail(
                f"Skill '{name}' not found. Available skills: {', '.join(available)}",
                skill_name=name,
            )
        return ToolResult.fail(
            f"Skill '{name}' not found. No skills are currently available. "
            "Skills should be placed in ~/.occ/skills/ or .occ/skills/",
            skill_name=name,
        )

    lines = [
        f"Skill '{skill.name}' loaded successfully.",
        "",
        f"Description: {skill.description}",
        "",
        "Instructions have been added to your system prompt. "
        "Follow the loaded skill's instructions for future tool calls.",
    ]
    if skill.allowed_tools:
        lines.append(
            "Tools are now narrowed to: "
            + ", ".join(skill.allowed_tools)
            + ". This cannot raise privilege above the session policy."
        )
    bundled = []
    for label, paths in (
        ("script", skill.scripts),
        ("example", skill.examples),
        ("asset", skill.assets),
    ):
        bundled.extend(f"  {label}: {path}" for path in paths)
    if bundled:
        lines.append(
            "Bundled files you may read_file or run_shell "
            "(they have not been executed):"
        )
        lines.extend(bundled)

    return ToolResult.ok(
        "\n".join(lines),
        skill_name=skill.name,
        allowed_tools=list(skill.allowed_tools),
    )
