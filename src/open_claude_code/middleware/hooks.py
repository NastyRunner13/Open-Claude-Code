"""A small, explicit runtime hook layer for local automation checks."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from open_claude_code.config import AgentConfig
from open_claude_code.middleware import Middleware


class HooksMiddleware(Middleware):
    """Run trusted configuration-owned command hooks around agent lifecycle events.

    Hook commands are intentionally opt-in in `occ.yml`: they execute local
    processes and should be treated like other project automation (for example
    a formatter or a policy checker), not as content supplied by the model.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._hooks = config.hooks if config else {}

    @property
    def name(self) -> str:
        return "hooks"

    def _entries(self, name: str) -> list[dict[str, Any]]:
        raw = self._hooks.get(name, [])
        if not isinstance(raw, list):
            return []
        entries: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                entries.append({"type": "command", "command": item})
            elif isinstance(item, dict):
                entries.append(item)
        return entries

    async def _run(self, name: str, **values: Any) -> tuple[bool, str]:
        for entry in self._entries(name):
            if entry.get("type", "command") != "command":
                continue
            command = entry.get("command")
            if not isinstance(command, str) or not command.strip():
                continue
            timeout = max(1, min(int(entry.get("timeout", 60)), 3600))
            environment = os.environ.copy()
            environment.update({f"OCC_{key.upper()}": str(value) for key, value in values.items()})
            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=environment,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except (OSError, asyncio.TimeoutError) as exc:
                return False, f"hook '{name}' failed: {exc}"
            if process.returncode:
                output = (stdout + stderr).decode("utf-8", errors="replace").strip()
                return False, f"hook '{name}' denied the operation (exit {process.returncode}): {output[:1000]}"
        return True, ""

    async def on_before_tool(self, tool_name: str, tool_params: dict[str, Any]) -> tuple[bool, str]:
        values = {
            "tool_name": tool_name,
            "file_path": tool_params.get("file_path", ""),
            "command": tool_params.get("command", ""),
        }
        for hook_name in ("pre_tool", f"pre_{tool_name}"):
            allowed, reason = await self._run(hook_name, **values)
            if not allowed:
                return False, reason
        return True, ""

    async def on_tool_result(self, tool_name: str, result: Any, tool_use_id: str = "") -> Any:
        if tool_name in {"write_file", "edit_file", "multi_edit", "apply_patch", "undo_edit"}:
            await self._run("post_edit", tool_name=tool_name, tool_use_id=tool_use_id)
        await self._run("post_tool", tool_name=tool_name, tool_use_id=tool_use_id)
        return result

    async def on_turn_end(self, response: str) -> None:
        await self._run("stop", response=response)
