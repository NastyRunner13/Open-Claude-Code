"""MCP (Model Context Protocol) client — connects to external tool servers.

MCP servers expose tools via a standardized protocol. This module:
1. Connects to MCP servers over stdio or SSE
2. Discovers available tools
3. Bridges MCP tools into OCC's native tool format
4. Handles tool invocation by proxying to the MCP server
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    command: str  # e.g., "npx -y @modelcontextprotocol/server-filesystem"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    """A tool discovered from an MCP server."""

    name: str
    description: str
    input_schema: dict
    server_name: str


class MCPClient:
    """Client for a single MCP server using stdio transport.

    Communicates via JSON-RPC over stdin/stdout with the MCP server process.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._tools: list[MCPTool] = []
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """Start the MCP server process and initialize the connection."""
        env = dict(self.config.env) if self.config.env else None

        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Start reading responses
        self._reader_task = asyncio.create_task(self._read_responses())

        # Initialize protocol
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "occ", "version": "0.2.0"},
        })

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

        # Discover tools
        result = await self._send_request("tools/list", {})
        if result and "tools" in result:
            self._tools = [
                MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                    server_name=self.config.name,
                )
                for t in result["tools"]
            ]

    async def disconnect(self) -> None:
        """Shut down the MCP server process."""
        if self._reader_task:
            self._reader_task.cancel()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()

    @property
    def tools(self) -> list[MCPTool]:
        """Tools discovered from this server."""
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Invoke a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })

        if result is None:
            return "Error: No response from MCP server"

        # Extract text from content blocks
        if "content" in result:
            parts = []
            for block in result["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(parts) if parts else json.dumps(result)

        return json.dumps(result)

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin:
            return None

        self._request_id += 1
        req_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        line = json.dumps(message) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        # Create a future for the response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        try:
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        line = json.dumps(message) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from the server's stdout."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break

                data = json.loads(line.decode().strip())
                req_id = data.get("id")

                if req_id and req_id in self._pending:
                    future = self._pending.pop(req_id)
                    if "error" in data:
                        future.set_result({"error": data["error"]})
                    else:
                        future.set_result(data.get("result"))

            except (json.JSONDecodeError, Exception):
                continue


class MCPManager:
    """Manages multiple MCP server connections.

    Handles connection lifecycle, tool aggregation, and namespacing.
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}

    async def add_server(self, config: MCPServerConfig) -> list[MCPTool]:
        """Connect to an MCP server and return its discovered tools."""
        client = MCPClient(config)
        try:
            await client.connect()
            self._clients[config.name] = client
            return client.tools
        except Exception as e:
            await client.disconnect()
            raise RuntimeError(f"Failed to connect to MCP server '{config.name}': {e}") from e

    async def remove_server(self, name: str) -> None:
        """Disconnect from an MCP server."""
        client = self._clients.pop(name, None)
        if client:
            await client.disconnect()

    async def shutdown(self) -> None:
        """Disconnect from all MCP servers."""
        for client in self._clients.values():
            await client.disconnect()
        self._clients.clear()

    @property
    def connected_servers(self) -> list[str]:
        """Names of currently connected servers."""
        return list(self._clients.keys())

    def get_all_tools(self) -> list[MCPTool]:
        """Get all tools from all connected servers."""
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool by name, routing to the correct server."""
        for client in self._clients.values():
            for tool in client.tools:
                if tool.name == tool_name:
                    return await client.call_tool(tool_name, arguments)
        return f"Error: Tool '{tool_name}' not found on any MCP server"

    def get_occ_tools(self) -> dict:
        """Convert all MCP tools into OCC's native tool format."""
        occ_tools = {}
        for tool in self.get_all_tools():
            # Prefix with mcp_ to avoid collisions with built-in tools
            occ_name = f"mcp_{tool.server_name}_{tool.name}"

            # Create a closure to capture the tool name
            async def make_caller(tn: str):
                async def caller(**kwargs: Any) -> str:
                    return await self.call_tool(tn, kwargs)
                return caller

            occ_tools[occ_name] = {
                "function": None,  # Will be set below
                "schema": {
                    "name": occ_name,
                    "description": f"[MCP:{tool.server_name}] {tool.description}",
                    "input_schema": tool.input_schema,
                },
                "_mcp_tool_name": tool.name,
                "_mcp_manager": self,
            }

        return occ_tools
