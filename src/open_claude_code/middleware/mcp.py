"""MCPMiddleware — wraps the existing MCPManager as composable middleware.

Handles MCP server lifecycle, tool aggregation, and /mcp slash commands
through the Middleware interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console

from open_claude_code.config import AgentConfig, save_config
from open_claude_code.mcp import MCPManager, MCPServerConfig
from open_claude_code.middleware import Middleware

if TYPE_CHECKING:
    from open_claude_code.agent import Agent

console = Console()


class MCPMiddleware(Middleware):
    """Middleware that integrates MCP (Model Context Protocol) servers.

    - Connects to configured MCP servers on startup
    - Injects MCP tools into the agent
    - Handles /mcp slash commands (list, add, remove)
    - Disconnects on shutdown
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._manager = MCPManager()
        self._config = config
        self._agent: Agent | None = None

    @property
    def name(self) -> str:
        return "mcp"

    @property
    def manager(self) -> MCPManager:
        """Access the underlying MCPManager."""
        return self._manager

    async def on_agent_start(self, agent: Agent) -> None:
        """Connect to configured MCP servers."""
        self._agent = agent
        if self._config:
            for s_conf in self._config.mcp_servers:
                try:
                    await self._manager.add_server(MCPServerConfig(**s_conf))
                except Exception as e:
                    console.print(
                        f"[bold red]Failed to connect to MCP server "
                        f"{s_conf.get('name')}: {e}[/]"
                    )

    def get_tools(self) -> dict[str, dict[str, Any]]:
        """Return MCP-provided tools in OCC format."""
        return self._manager.get_occ_tools()

    async def on_shutdown(self) -> None:
        """Disconnect from all MCP servers."""
        await self._manager.shutdown()

    def handle_slash_command(self, cmd: str, rest: str) -> str | None:
        """Handle /mcp slash commands. Note: add/remove are async but we return sync."""
        if cmd != "/mcp":
            return None

        # For async operations, we return a marker that main.py handles
        if rest.startswith("add ") or rest.startswith("remove "):
            # Return the command for async handling
            return f"mcp_async:{rest}"

        if not rest or rest == "list":
            servers = self._manager.connected_servers
            if not servers:
                console.print("  No MCP servers connected.", style="dim")
            else:
                console.print("  Connected MCP servers:")
                for s in servers:
                    console.print(f"  • [bold cyan]{s}[/]")
            console.print()
            return "handled"

        console.print("  Usage: /mcp [list | add <name> <command> [args] | remove <name>]")
        console.print()
        return "handled"

    async def handle_async_command(self, rest: str) -> None:
        """Handle async MCP operations (add/remove servers)."""
        if rest.startswith("add "):
            parts = rest[4:].strip().split()
            if len(parts) < 2:
                console.print("  Usage: /mcp add <name> <command> [args...]", style="dim red")
                return

            name, command, *args = parts
            server_config = MCPServerConfig(name=name, command=command, args=args)
            try:
                with console.status(
                    f"[dim]Connecting to MCP server '{name}'...[/]", spinner="dots"
                ):
                    tools = await self._manager.add_server(server_config)

                # Refresh agent tools
                if self._agent:
                    self._agent.tools.update(self._manager.get_occ_tools())

                # Persist to config
                if self._config:
                    self._config.mcp_servers.append(
                        {"name": name, "command": command, "args": args}
                    )
                    save_config(self._config)

                console.print(
                    f"  Successfully connected to [bold cyan]{name}[/] "
                    f"and loaded {len(tools)} tools."
                )
            except Exception as e:
                console.print(f"  Failed to connect: {e}", style="bold red")

        elif rest.startswith("remove "):
            name = rest[7:].strip()
            if name in self._manager.connected_servers:
                with console.status(
                    f"[dim]Disconnecting from '{name}'...[/]", spinner="dots"
                ):
                    await self._manager.remove_server(name)

                # Remove tools from agent
                if self._agent:
                    prefix = f"mcp_{name}_"
                    self._agent.tools = {
                        k: v for k, v in self._agent.tools.items()
                        if not k.startswith(prefix)
                    }

                # Update config
                if self._config:
                    self._config.mcp_servers = [
                        s for s in self._config.mcp_servers if s.get("name") != name
                    ]
                    save_config(self._config)

                console.print(
                    f"  Disconnected and removed server [bold cyan]{name}[/]."
                )
            else:
                console.print(f"  Server '{name}' not found.", style="dim red")

        console.print()
