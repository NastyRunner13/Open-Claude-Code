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
        path.write_text("model: gpt-4o\nmax_tokens: 32000\nskip_approval: true\nmode: plan\n")
        config = _parse_config(path)
        assert config.model == "gpt-4o"
        assert config.max_tokens == 32000
        assert config.skip_approval is True
        assert config.mode == "plan"

    def test_empty_config(self, tmp_path):
        path = tmp_path / "occ.yml"
        path.write_text("")
        config = _parse_config(path)
        assert config.model == "claude-sonnet-4-20250514"
