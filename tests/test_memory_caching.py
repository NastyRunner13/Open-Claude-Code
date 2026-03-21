"""Tests for the memory system and prompt caching."""

import os
import tempfile
from pathlib import Path

import pytest

from open_claude_code.middleware.memory import MemoryMiddleware, MEMORY_FILE_NAMES
from open_claude_code.providers.anthropic import AnthropicProvider


# ── MemoryMiddleware tests ─────────────────────────────────────────

class TestMemoryMiddleware:
    """Tests for project memory file loading."""

    def test_name(self):
        mw = MemoryMiddleware()
        assert mw.name == "memory"

    def test_no_files_loaded_initially(self):
        """When no memory files exist, nothing is loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()
            assert len(mw.loaded_files) == 0

    def test_loads_agents_md(self):
        """Discovers and loads AGENTS.md."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_file = Path(tmp) / "AGENTS.md"
            agents_file.write_text("# Project Rules\nAlways use type hints.", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 1
            assert "AGENTS.md" in list(mw.loaded_files.keys())[0]
            content = list(mw.loaded_files.values())[0]
            assert "type hints" in content

    def test_loads_claude_md(self):
        """Discovers and loads CLAUDE.md."""
        with tempfile.TemporaryDirectory() as tmp:
            claude_file = Path(tmp) / "CLAUDE.md"
            claude_file.write_text("Use Python 3.12+", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 1
            assert "Python 3.12" in list(mw.loaded_files.values())[0]

    def test_loads_occ_memory(self):
        """Discovers .occ/memory.md."""
        with tempfile.TemporaryDirectory() as tmp:
            occ_dir = Path(tmp) / ".occ"
            occ_dir.mkdir()
            mem_file = occ_dir / "memory.md"
            mem_file.write_text("Project conventions here.", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 1

    def test_loads_multiple_files(self):
        """Loads all matching memory files."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "AGENTS.md").write_text("Agents rules", encoding="utf-8")
            (Path(tmp) / "CLAUDE.md").write_text("Claude rules", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 2

    def test_prompt_additions_empty(self):
        """No prompt when no memory files loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()
            assert mw.get_prompt_additions() == ""

    def test_prompt_additions_with_files(self):
        """Prompt includes loaded memory content."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "AGENTS.md").write_text("Always test your code.", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            prompt = mw.get_prompt_additions()
            assert "Project Memory" in prompt
            assert "Always test your code" in prompt
            assert "AGENTS.md" in prompt

    def test_truncation(self):
        """Long memory files are truncated."""
        with tempfile.TemporaryDirectory() as tmp:
            long_content = "A" * 10000
            (Path(tmp) / "AGENTS.md").write_text(long_content, encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp], max_memory_chars=100)
            mw._scan_and_load()

            prompt = mw.get_prompt_additions()
            assert "truncated" in prompt.lower()

    def test_skips_empty_files(self):
        """Empty files are not loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "AGENTS.md").write_text("", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 0

    def test_slash_command_list(self):
        """Handles /memory list command."""
        mw = MemoryMiddleware()
        result = mw.handle_slash_command("/memory", "list")
        assert result == "handled"

    def test_slash_command_show(self):
        """Handles /memory show command."""
        mw = MemoryMiddleware()
        result = mw.handle_slash_command("/memory", "show")
        assert result == "handled"

    def test_slash_command_reload(self):
        """Handles /memory reload command."""
        mw = MemoryMiddleware()
        result = mw.handle_slash_command("/memory", "reload")
        assert result == "handled"

    def test_slash_command_unhandled(self):
        """Ignores non-memory slash commands."""
        mw = MemoryMiddleware()
        result = mw.handle_slash_command("/skill", "list")
        assert result is None

    def test_multiple_search_dirs(self):
        """Scans multiple directories."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            (Path(tmp1) / "AGENTS.md").write_text("Dir 1 rules", encoding="utf-8")
            (Path(tmp2) / "CLAUDE.md").write_text("Dir 2 rules", encoding="utf-8")

            mw = MemoryMiddleware(search_dirs=[tmp1, tmp2])
            mw._scan_and_load()

            assert len(mw.loaded_files) == 2


# ── AnthropicProvider prompt caching tests ─────────────────────────

class TestPromptCaching:
    """Tests for Anthropic prompt caching logic."""

    def _make_provider(self, caching: bool = True) -> AnthropicProvider:
        """Create a provider without connecting."""
        return AnthropicProvider(
            model="claude-sonnet-4-20250514",
            max_tokens=8000,
            api_key="test-key",
            prompt_caching=caching,
        )

    def test_cache_enabled_system_blocks(self):
        """With caching enabled, system prompt becomes content blocks."""
        p = self._make_provider(caching=True)
        result = p._build_system_blocks("You are a helpful assistant")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_disabled_system_string(self):
        """With caching disabled, system prompt stays as string."""
        p = self._make_provider(caching=False)
        result = p._build_system_blocks("You are a helpful assistant")
        assert isinstance(result, str)
        assert result == "You are a helpful assistant"

    def test_cache_splits_base_and_additions(self):
        """System prompt is split: base is cached, additions are not."""
        p = self._make_provider(caching=True)
        prompt = "You are an assistant\n\n## Current Plan\nStep 1: foo"
        result = p._build_system_blocks(prompt)

        assert isinstance(result, list)
        assert len(result) == 2
        # First block (base) is cached
        assert "cache_control" in result[0]
        assert result[0]["text"] == "You are an assistant"
        # Second block (dynamic) is NOT cached
        assert "cache_control" not in result[1]
        assert "Current Plan" in result[1]["text"]

    def test_message_caching_early_messages(self):
        """First few messages get cache markers."""
        p = self._make_provider(caching=True)
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How's it going?"},
        ]
        cached = p._add_message_caching(messages)

        # First user message should be cached (converted to list)
        assert isinstance(cached[0]["content"], list)
        assert cached[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

        # First assistant message should be cached
        assert isinstance(cached[1]["content"], list)
        assert cached[1]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_message_caching_disabled(self):
        """With caching disabled, messages are untouched."""
        p = self._make_provider(caching=False)
        messages = [{"role": "user", "content": "Hello"}]
        cached = p._add_message_caching(messages)

        assert cached[0]["content"] == "Hello"

    def test_message_caching_max_points(self):
        """Only 2 cache points are added to messages."""
        p = self._make_provider(caching=True)
        messages = [
            {"role": "user", "content": "One"},
            {"role": "assistant", "content": "Two"},
            {"role": "user", "content": "Three"},
            {"role": "assistant", "content": "Four"},
        ]
        cached = p._add_message_caching(messages)

        # Count cache points
        cache_count = 0
        for msg in cached:
            content = msg["content"]
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and "cache_control" in block:
                        cache_count += 1

        assert cache_count == 2

    def test_message_caching_short_conversation(self):
        """Short conversations (< 2 messages) are not cached."""
        p = self._make_provider(caching=True)
        messages = [{"role": "user", "content": "Hi"}]
        cached = p._add_message_caching(messages)

        # Single message shouldn't be modified
        assert cached == messages

    def test_prompt_caching_default_true(self):
        """Prompt caching defaults to enabled."""
        p = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="test")
        assert p.prompt_caching is True
