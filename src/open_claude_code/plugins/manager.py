"""Plugin system — extensible hooks for agent lifecycle events.

Plugins are Python modules with a PLUGIN.py or plugin.py entry point
that defines a `register(hooks)` function. The hooks object provides
registration methods for various lifecycle events.

Plugin directory structure:
  plugins/
    my-plugin/
      plugin.py      # Must define register(hooks)
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine


# Hook types
HookFn = Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    name: str
    path: Path
    description: str = ""


class PluginHooks:
    """Hook registry that plugins use to register their callbacks.

    Supported hooks:
      - on_agent_start(config) → called when agent initializes
      - on_before_send(messages, tools) → can modify messages/tools before LLM call
      - on_after_response(response) → called after LLM responds
      - on_tool_result(tool_name, result) → can modify tool results
      - on_agent_stop() → called when agent session ends
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = {
            "on_agent_start": [],
            "on_before_send": [],
            "on_after_response": [],
            "on_tool_result": [],
            "on_agent_stop": [],
        }

    def on_agent_start(self, fn: HookFn) -> None:
        """Register a hook called when the agent starts."""
        self._hooks["on_agent_start"].append(fn)

    def on_before_send(self, fn: HookFn) -> None:
        """Register a hook called before sending messages to the LLM."""
        self._hooks["on_before_send"].append(fn)

    def on_after_response(self, fn: HookFn) -> None:
        """Register a hook called after receiving an LLM response."""
        self._hooks["on_after_response"].append(fn)

    def on_tool_result(self, fn: HookFn) -> None:
        """Register a hook called after a tool returns a result."""
        self._hooks["on_tool_result"].append(fn)

    def on_agent_stop(self, fn: HookFn) -> None:
        """Register a hook called when the agent session ends."""
        self._hooks["on_agent_stop"].append(fn)

    async def emit(self, hook_name: str, **kwargs: Any) -> Any:
        """Emit a hook event, calling all registered handlers."""
        result = None
        for fn in self._hooks.get(hook_name, []):
            result = await fn(**kwargs)
        return result

    def get_hooks(self, hook_name: str) -> list[HookFn]:
        """Get all registered handlers for a hook."""
        return self._hooks.get(hook_name, [])


class PluginManager:
    """Manages plugin discovery, loading, and hook dispatching."""

    def __init__(self, search_dirs: list[str] | None = None) -> None:
        self._search_dirs = [
            Path(d).expanduser() for d in (search_dirs or ["~/.occ/plugins", ".occ/plugins"])
        ]
        self.hooks = PluginHooks()
        self._loaded: dict[str, PluginInfo] = {}

    def scan_and_load(self) -> list[PluginInfo]:
        """Scan plugin directories and load all valid plugins."""
        loaded = []
        for search_dir in self._search_dirs:
            if not search_dir.exists():
                continue
            for plugin_dir in search_dir.iterdir():
                if plugin_dir.is_dir():
                    info = self._try_load(plugin_dir)
                    if info:
                        loaded.append(info)
        return loaded

    def _try_load(self, plugin_dir: Path) -> PluginInfo | None:
        """Try to load a plugin from a directory."""
        # Look for plugin.py or PLUGIN.py
        for name in ("plugin.py", "PLUGIN.py"):
            plugin_file = plugin_dir / name
            if plugin_file.exists():
                return self._load_module(plugin_file, plugin_dir.name)
        return None

    def _load_module(self, path: Path, name: str) -> PluginInfo | None:
        """Load a plugin module and call its register function."""
        try:
            spec = importlib.util.spec_from_file_location(f"occ_plugin_{name}", path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"occ_plugin_{name}"] = module
            spec.loader.exec_module(module)

            # Call register(hooks) if it exists
            register_fn = getattr(module, "register", None)
            if register_fn and callable(register_fn):
                register_fn(self.hooks)

            info = PluginInfo(
                name=getattr(module, "PLUGIN_NAME", name),
                path=path.parent,
                description=getattr(module, "PLUGIN_DESCRIPTION", ""),
            )
            self._loaded[info.name] = info
            return info

        except Exception:
            return None

    @property
    def loaded(self) -> dict[str, PluginInfo]:
        """Currently loaded plugins."""
        return dict(self._loaded)

    def list_formatted(self) -> str:
        """Return a formatted listing of loaded plugins."""
        if not self._loaded:
            return "No plugins loaded. Place plugins in ~/.occ/plugins/ or .occ/plugins/"

        lines = ["Loaded Plugins:"]
        for name, info in self._loaded.items():
            desc = f" — {info.description}" if info.description else ""
            lines.append(f"  • {name}{desc}")
        return "\n".join(lines)
