"""Tests for the configuration system."""

from pathlib import Path

import pytest

from open_claude_code.config import AgentConfig, load_config, _parse_config


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig()
        assert config.model == "claude-sonnet-4-20250514"
        assert config.max_tokens == 16000
        assert config.mode == "agent"
        assert config.skip_approval is False
        assert "read_file" in config.auto_approve

    def test_custom_values(self):
        config = AgentConfig(model="gpt-4o", mode="ask", skip_approval=True)
        assert config.model == "gpt-4o"
        assert config.mode == "ask"
        assert config.skip_approval is True


class TestLoadConfig:
    def test_no_config_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.model == "claude-sonnet-4-20250514"

    def test_explicit_path(self, tmp_path):
        path = tmp_path / "occ.yml"
        path.write_text("model: claude-opus-4-6\nmax_tokens: 32000\n")
        config = load_config(path)
        assert config.model == "claude-opus-4-6"
        assert config.max_tokens == 32000

    def test_missing_path_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yml")

    def test_auto_detect(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "occ.yml").write_text("model: gpt-4o\nmode: ask\n")
        config = load_config()
        assert config.model == "gpt-4o"
        assert config.mode == "ask"


class TestParseConfig:
    def test_full_config(self, tmp_path):
        path = tmp_path / "occ.yml"
        path.write_text(
            "model: gpt-4o\n"
            "max_tokens: 32000\n"
            "max_tool_output: 1234\n"
            "skip_approval: true\n"
            "mode: plan\n"
            "permission_mode: read-only\n"
            "disallowed_tools:\n"
            "  - mcp_production_*\n"
            "workspace_roots:\n"
            "  - src\n"
            "writable_roots:\n"
            "  - src\n"
            "shell_policy: read-only\n"
            "persist_sessions: false\n"
            "sessions_dir: custom-sessions\n"
        )
        config = _parse_config(path)
        assert config.model == "gpt-4o"
        assert config.max_tokens == 32000
        assert config.max_tool_output == 1234
        assert config.skip_approval is True
        assert config.mode == "plan"
        assert config.permission_mode == "read-only"
        assert config.disallowed_tools == ["mcp_production_*"]
        assert config.workspace_roots == ["src"]
        assert config.writable_roots == ["src"]
        assert config.shell_policy == "read-only"
        assert config.persist_sessions is False
        assert config.sessions_dir == "custom-sessions"

    def test_empty_config(self, tmp_path):
        path = tmp_path / "occ.yml"
        path.write_text("")
        config = _parse_config(path)
        assert config.model == "claude-sonnet-4-20250514"
