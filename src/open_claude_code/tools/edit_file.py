"""Edit file tool — exact string replacement for surgical edits."""

SCHEMA = {
    "name": "edit_file",
    "description": (
        "Edit a file by replacing an exact string with a new string. "
        "The old_string must appear exactly once in the file. "
        "Always read the file first to see its current contents before editing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "The exact string to find and replace. "
                    "Must appear exactly once in the file. "
                    "Include enough surrounding context to make it unique."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace old_string with.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
}


async def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string. old_string must be unique in the file."""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
    except (FileNotFoundError, PermissionError) as e:
        return f"Error: {e}"

    if not old_string:
        return "Error: old_string cannot be empty"

    first = content.find(old_string)
    if first == -1:
        return "Error: old_string not found in file"
    if content.find(old_string, first + 1) != -1:
        return "Error: old_string is not unique — provide more surrounding context"

    new_content = content[:first] + new_string + content[first + len(old_string):]

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return f"Successfully edited {file_path}"
