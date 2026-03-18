"""Tool registry — collects and exposes all tools to the agent."""

from open_claude_code.tools.edit_file import SCHEMA as EDIT_FILE_SCHEMA
from open_claude_code.tools.edit_file import edit_file
from open_claude_code.tools.find_files import SCHEMA as FIND_FILES_SCHEMA
from open_claude_code.tools.find_files import find_files
from open_claude_code.tools.grep_search import SCHEMA as GREP_SEARCH_SCHEMA
from open_claude_code.tools.grep_search import grep_search
from open_claude_code.tools.list_directory import SCHEMA as LIST_DIRECTORY_SCHEMA
from open_claude_code.tools.list_directory import list_directory
from open_claude_code.tools.read_file import SCHEMA as READ_FILE_SCHEMA
from open_claude_code.tools.read_file import read_file
from open_claude_code.tools.read_url import SCHEMA as READ_URL_SCHEMA
from open_claude_code.tools.read_url import read_url
from open_claude_code.tools.run_shell import SCHEMA as RUN_SHELL_SCHEMA
from open_claude_code.tools.run_shell import run_shell
from open_claude_code.tools.sandbox import SCHEMA as SANDBOX_SCHEMA
from open_claude_code.tools.sandbox import sandbox
from open_claude_code.tools.spawn_agent import SCHEMA as SPAWN_AGENT_SCHEMA
from open_claude_code.tools.web_search import SCHEMA as WEB_SEARCH_SCHEMA
from open_claude_code.tools.web_search import web_search
from open_claude_code.tools.write_file import SCHEMA as WRITE_FILE_SCHEMA
from open_claude_code.tools.write_file import write_file


def get_tools() -> dict:
    """Return the full tool registry."""
    return {
        "read_file": {
            "function": read_file,
            "schema": READ_FILE_SCHEMA,
        },
        "write_file": {
            "function": write_file,
            "schema": WRITE_FILE_SCHEMA,
        },
        "edit_file": {
            "function": edit_file,
            "schema": EDIT_FILE_SCHEMA,
        },
        "list_directory": {
            "function": list_directory,
            "schema": LIST_DIRECTORY_SCHEMA,
        },
        "find_files": {
            "function": find_files,
            "schema": FIND_FILES_SCHEMA,
        },
        "grep_search": {
            "function": grep_search,
            "schema": GREP_SEARCH_SCHEMA,
        },
        "run_shell": {
            "function": run_shell,
            "schema": RUN_SHELL_SCHEMA,
        },
        "web_search": {
            "function": web_search,
            "schema": WEB_SEARCH_SCHEMA,
        },
        "read_url": {
            "function": read_url,
            "schema": READ_URL_SCHEMA,
        },
        "sandbox": {
            "function": sandbox,
            "schema": SANDBOX_SCHEMA,
        },
        "spawn_agent": {
            "function": None,  # Handled directly by the agent loop
            "schema": SPAWN_AGENT_SCHEMA,
        },
    }
