"""Tests for ToolResult and LLM-powered context summarization."""

import pytest

from open_claude_code.tools.result import ToolResult
from open_claude_code.context import (
    ContextManager,
    ContextStats,
    estimate_tokens,
    estimate_message_tokens,
    _naive_summary,
    _extract_text_from_messages,
)


# ── ToolResult tests ───────────────────────────────────────────────

class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_ok_with_string(self):
        r = ToolResult.ok("file contents here")
        assert r.success is True
        assert r.data == "file contents here"
        assert r.error is None
        assert str(r) == "file contents here"

    def test_ok_with_none(self):
        r = ToolResult.ok()
        assert str(r) == "OK"

    def test_ok_with_dict(self):
        r = ToolResult.ok({"key": "value"})
        assert r.success is True
        assert str(r) == "{'key': 'value'}"

    def test_fail(self):
        r = ToolResult.fail("file not found")
        assert r.success is False
        assert r.error == "file not found"
        assert str(r) == "Error: file not found"

    def test_fail_no_message(self):
        r = ToolResult(success=False)
        assert str(r) == "Error: unknown error"

    def test_metadata(self):
        r = ToolResult.ok("done", file_path="/foo", bytes_written=42)
        assert r.metadata == {"file_path": "/foo", "bytes_written": 42}

    def test_is_error(self):
        assert ToolResult.fail("oops").is_error is True
        assert ToolResult.ok("done").is_error is False

    def test_backward_compat_string_conversion(self):
        """ToolResult.__str__() matches old-style string returns."""
        # Success case
        r = ToolResult.ok("Successfully wrote 100 characters to foo.py")
        assert str(r) == "Successfully wrote 100 characters to foo.py"

        # Error case
        r = ToolResult.fail("[Errno 2] No such file or directory: 'foo.py'")
        assert str(r) == "Error: [Errno 2] No such file or directory: 'foo.py'"


# ── Tool return type tests ─────────────────────────────────────────

class TestToolsReturnToolResult:
    """Verify that tools return ToolResult instead of raw strings."""

    @pytest.mark.asyncio
    async def test_read_file_returns_tool_result(self, tmp_path):
        from open_claude_code.tools.read_file import read_file
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        result = await read_file(str(f))
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "hello" in str(result)

    @pytest.mark.asyncio
    async def test_read_file_error_returns_tool_result(self):
        from open_claude_code.tools.read_file import read_file
        result = await read_file("/nonexistent/path")
        assert isinstance(result, ToolResult)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_file_returns_tool_result(self, tmp_path):
        from open_claude_code.tools.write_file import write_file
        f = tmp_path / "out.txt"
        result = await write_file(str(f), "content")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.metadata.get("bytes_written") == 7

    @pytest.mark.asyncio
    async def test_edit_file_returns_tool_result(self, tmp_path):
        from open_claude_code.tools.edit_file import edit_file
        f = tmp_path / "edit.txt"
        f.write_text("hello world", encoding="utf-8")
        result = await edit_file(str(f), "hello", "goodbye")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.metadata.get("chars_removed") == 5
        assert result.metadata.get("chars_added") == 7

    @pytest.mark.asyncio
    async def test_list_directory_returns_tool_result(self, tmp_path):
        from open_claude_code.tools.list_directory import list_directory
        (tmp_path / "file.txt").touch()
        result = await list_directory(str(tmp_path))
        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_find_files_returns_tool_result(self, tmp_path):
        from open_claude_code.tools.find_files import find_files
        (tmp_path / "test.py").touch()
        result = await find_files("*.py", str(tmp_path))
        assert isinstance(result, ToolResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_sandbox_returns_tool_result(self):
        from open_claude_code.tools.sandbox import sandbox
        result = await sandbox("print('hi')", "python")
        assert isinstance(result, ToolResult)

    @pytest.mark.asyncio
    async def test_sandbox_unsupported_lang(self):
        from open_claude_code.tools.sandbox import sandbox
        result = await sandbox("code", "ruby")
        assert isinstance(result, ToolResult)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_load_skill_no_manager(self):
        from open_claude_code.tools.load_skill import load_skill
        result = await load_skill("test")
        assert isinstance(result, ToolResult)
        assert result.success is False


# ── Context Manager tests ──────────────────────────────────────────

class TestContextManager:
    """Tests for the updated ContextManager."""

    def test_stats(self):
        cm = ContextManager(max_context_tokens=1000)
        history = [{"role": "user", "content": "a" * 400}]
        stats = cm.get_stats(history)
        assert stats.message_count == 1
        assert stats.estimated_tokens == 100  # 400 chars / 4

    def test_needs_compaction(self):
        cm = ContextManager(max_context_tokens=100, compaction_threshold=0.5)
        # 800 chars = 200 tokens, well above 50% of 100
        history = [{"role": "user", "content": "x" * 800}]
        assert cm.needs_compaction(history) is True

    def test_no_compaction_needed(self):
        cm = ContextManager(max_context_tokens=10000)
        history = [{"role": "user", "content": "hello"}]
        assert cm.needs_compaction(history) is False

    @pytest.mark.asyncio
    async def test_compact_short_history(self):
        cm = ContextManager(keep_recent=20)
        history = [{"role": "user", "content": "hi"}]
        result = await cm.compact(history)
        assert result == history

    @pytest.mark.asyncio
    async def test_compact_naive_fallback(self):
        """Without provider, uses naive summary."""
        cm = ContextManager(keep_recent=2, provider=None)
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            *[{"role": "user", "content": f"msg {i}"} for i in range(10)],
            {"role": "user", "content": "recent1"},
            {"role": "assistant", "content": "recent2"},
        ]
        result = await cm.compact(history)
        # Should have: first 2 + summary + last 2
        assert len(result) == 5
        assert "compacted" in result[2]["content"].lower()

    def test_naive_summary(self):
        messages = [
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "I'll help with that"},
        ]
        summary = _naive_summary(messages)
        assert "2 messages" in summary
        assert "Topics covered" in summary

    def test_extract_text(self):
        messages = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "read_file", "input": {"path": "x"}},
            ]},
        ]
        text = _extract_text_from_messages(messages)
        assert "[user]: Hello world" in text
        assert "read_file" in text

    @pytest.mark.asyncio
    async def test_auto_compact_async_no_compaction(self):
        cm = ContextManager(max_context_tokens=100000)
        history = [{"role": "user", "content": "hi"}]
        result = await cm.auto_compact_async(history)
        assert result is history  # Same object, no change

    def test_auto_compact_sync_fallback(self):
        cm = ContextManager(max_context_tokens=100, keep_recent=2)
        history = [
            {"role": "user", "content": "x" * 400},
            {"role": "assistant", "content": "y" * 400},
            *[{"role": "user", "content": f"z{i}" * 100} for i in range(5)],
            {"role": "user", "content": "recent1"},
            {"role": "assistant", "content": "recent2"},
        ]
        result = cm.auto_compact(history)
        assert len(result) < len(history)
