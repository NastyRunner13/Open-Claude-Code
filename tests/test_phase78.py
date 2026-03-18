"""Tests for MCP client, plugin system, and context management."""

import asyncio
from pathlib import Path

from open_claude_code.context import ContextManager, ContextStats, estimate_tokens
from open_claude_code.mcp.client import MCPManager, MCPServerConfig, MCPTool
from open_claude_code.plugins.manager import PluginHooks, PluginInfo, PluginManager


# ── Context Manager Tests ─────────────────────────────────────────


class TestTokenEstimation:
    def test_basic_estimation(self):
        assert estimate_tokens("hello world") >= 1
        assert estimate_tokens("a" * 100) == 25  # ~4 chars per token

    def test_empty_string(self):
        assert estimate_tokens("") == 1  # Minimum 1


class TestContextManager:
    def test_stats(self):
        cm = ContextManager(max_context_tokens=1000)
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        stats = cm.get_stats(history)
        assert stats.message_count == 2
        assert stats.estimated_tokens > 0
        assert 0 < stats.utilization < 1

    def test_needs_compaction_below_threshold(self):
        cm = ContextManager(max_context_tokens=100000)
        history = [{"role": "user", "content": "Hi"}]
        assert not cm.needs_compaction(history)

    def test_needs_compaction_above_threshold(self):
        cm = ContextManager(max_context_tokens=10, compaction_threshold=0.5)
        history = [{"role": "user", "content": "a" * 100}]
        assert cm.needs_compaction(history)

    def test_compact_short_history(self):
        cm = ContextManager(keep_recent=5)
        history = [{"role": "user", "content": f"msg {i}"} for i in range(3)]
        result = cm.compact(history)
        assert len(result) == 3  # No compaction needed

    def test_compact_long_history(self):
        cm = ContextManager(keep_recent=5)
        history = [{"role": "user", "content": f"Message number {i}"} for i in range(30)]
        result = cm.compact(history)
        # Should be: 2 first + 1 summary + 5 recent = 8
        assert len(result) == 8
        # Summary message should exist
        assert "compacted" in result[2]["content"].lower()
        # Recent messages preserved
        assert result[-1]["content"] == "Message number 29"

    def test_auto_compact_when_needed(self):
        cm = ContextManager(max_context_tokens=50, compaction_threshold=0.5, keep_recent=3)
        history = [{"role": "user", "content": "a" * 100} for _ in range(20)]
        result = cm.auto_compact(history)
        assert len(result) < len(history)

    def test_auto_compact_when_not_needed(self):
        cm = ContextManager(max_context_tokens=100000)
        history = [{"role": "user", "content": "Hi"}]
        result = cm.auto_compact(history)
        assert len(result) == len(history)

    def test_compact_preserves_first_messages(self):
        cm = ContextManager(keep_recent=3)
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        result = cm.compact(history)
        assert result[0]["content"] == "msg 0"
        assert result[1]["content"] == "msg 1"

    def test_compact_with_tool_blocks(self):
        cm = ContextManager(keep_recent=3)
        history = [
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "ok"},
        ]
        # Add tool call messages
        for i in range(15):
            history.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"path": "f.py"}},
            ]})
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"content {i}"},
            ]})

        result = cm.compact(history)
        assert len(result) < len(history)
        # Summary should mention tool operations
        summary = result[2]["content"]
        assert "tool operations" in summary.lower()


# ── Plugin System Tests ────────────────────────────────────────────


class TestPluginHooks:
    def test_register_and_emit(self):
        hooks = PluginHooks()
        called = []

        async def on_start(**kwargs):
            called.append("started")

        hooks.on_agent_start(on_start)

        asyncio.run(hooks.emit("on_agent_start"))
        assert called == ["started"]

    def test_multiple_hooks(self):
        hooks = PluginHooks()
        order = []

        async def hook1(**kwargs):
            order.append(1)

        async def hook2(**kwargs):
            order.append(2)

        hooks.on_agent_start(hook1)
        hooks.on_agent_start(hook2)

        asyncio.run(hooks.emit("on_agent_start"))
        assert order == [1, 2]

    def test_all_hook_types(self):
        hooks = PluginHooks()
        for hook_name in ["on_agent_start", "on_before_send", "on_after_response", "on_tool_result", "on_agent_stop"]:
            assert hooks.get_hooks(hook_name) == []

    def test_unknown_hook(self):
        hooks = PluginHooks()
        result = asyncio.run(hooks.emit("nonexistent"))
        assert result is None


class TestPluginManager:
    def test_loads_plugin(self, tmp_path):
        plugin_dir = tmp_path / "plugins" / "test-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.py").write_text(
            'PLUGIN_NAME = "Test Plugin"\n'
            'PLUGIN_DESCRIPTION = "A test plugin"\n'
            'def register(hooks):\n'
            '    pass\n'
        )

        pm = PluginManager(search_dirs=[str(tmp_path / "plugins")])
        loaded = pm.scan_and_load()
        assert len(loaded) == 1
        assert loaded[0].name == "Test Plugin"
        assert "Test Plugin" in pm.loaded

    def test_plugin_with_hooks(self, tmp_path):
        plugin_dir = tmp_path / "plugins" / "hooky"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.py").write_text(
            'calls = []\n'
            'async def on_start(**kwargs):\n'
            '    calls.append("start")\n'
            'def register(hooks):\n'
            '    hooks.on_agent_start(on_start)\n'
        )

        pm = PluginManager(search_dirs=[str(tmp_path / "plugins")])
        pm.scan_and_load()

        asyncio.run(pm.hooks.emit("on_agent_start"))
        assert len(pm.hooks.get_hooks("on_agent_start")) == 1

    def test_empty_directory(self, tmp_path):
        pm = PluginManager(search_dirs=[str(tmp_path / "nonexistent")])
        loaded = pm.scan_and_load()
        assert len(loaded) == 0

    def test_list_formatted_no_plugins(self, tmp_path):
        pm = PluginManager(search_dirs=[str(tmp_path / "empty")])
        result = pm.list_formatted()
        assert "No plugins loaded" in result

    def test_list_formatted_with_plugins(self, tmp_path):
        plugin_dir = tmp_path / "plugins" / "fmt"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.py").write_text(
            'PLUGIN_NAME = "Formatter"\n'
            'PLUGIN_DESCRIPTION = "Formats things"\n'
            'def register(hooks): pass\n'
        )

        pm = PluginManager(search_dirs=[str(tmp_path / "plugins")])
        pm.scan_and_load()
        result = pm.list_formatted()
        assert "Formatter" in result
        assert "Formats things" in result

    def test_skips_invalid_plugin(self, tmp_path):
        plugin_dir = tmp_path / "plugins" / "broken"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.py").write_text("raise RuntimeError('broken!')")

        pm = PluginManager(search_dirs=[str(tmp_path / "plugins")])
        loaded = pm.scan_and_load()
        assert len(loaded) == 0  # gracefully skipped


# ── MCP Tests ──────────────────────────────────────────────────────


class TestMCPServerConfig:
    def test_config_creation(self):
        config = MCPServerConfig(
            name="test",
            command="echo",
            args=["hello"],
            env={"KEY": "val"},
        )
        assert config.name == "test"
        assert config.command == "echo"

    def test_config_defaults(self):
        config = MCPServerConfig(name="test", command="echo")
        assert config.args == []
        assert config.env == {}


class TestMCPTool:
    def test_tool_creation(self):
        tool = MCPTool(
            name="read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            server_name="fs",
        )
        assert tool.name == "read"
        assert tool.server_name == "fs"


class TestMCPManager:
    def test_initial_state(self):
        manager = MCPManager()
        assert manager.connected_servers == []
        assert manager.get_all_tools() == []

    def test_get_occ_tools_empty(self):
        manager = MCPManager()
        tools = manager.get_occ_tools()
        assert tools == {}

    def test_call_tool_not_found(self):
        manager = MCPManager()
        result = asyncio.run(manager.call_tool("nonexistent", {}))
        assert "not found" in result.lower()
