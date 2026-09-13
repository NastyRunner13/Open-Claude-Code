"""PR23: `/provider` wizard + user-level saved profiles. No keys in the ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from open_claude_code import profiles
from open_claude_code.config import AgentConfig, load_config
from open_claude_code.doctor import collect_doctor_report
from open_claude_code.main import (
    check_provider_auth,
    handle_slash_command,
    parse_args,
    resolve_config,
    run_provider_command,
    switch_provider_in_session,
)
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.planning import PlanningMiddleware


def _isolate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCC_PROFILES_PATH", str(tmp_path / "profiles.yml"))
    monkeypatch.setenv("OCC_CACHE_DIR", str(tmp_path / "cache"))
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OCC_MODEL",
        "OCC_PROFILE",
    ):
        monkeypatch.delenv(key, raising=False)


def _slash_env():
    config = AgentConfig()
    agent = MagicMock()
    agent.history = []
    agent.cost_tracker = MagicMock()
    mgr = MiddlewareManager([PlanningMiddleware()])
    return config, agent, mgr


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    saved = profiles.save_profile("work", "openrouter/anthropic/claude-sonnet-4")
    assert saved.name == "work"
    assert saved.model == "openrouter/anthropic/claude-sonnet-4"
    data = profiles.load_profiles_file()
    assert data["active"] == "work"
    assert data["profiles"]["work"]["model"] == "openrouter/anthropic/claude-sonnet-4"
    assert "api_key" not in data["profiles"]["work"]


def test_invalid_profile_names_rejected(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        profiles.save_profile("", "gpt-4o")
    with pytest.raises(ValueError):
        profiles.save_profile("has spaces!", "gpt-4o")
    with pytest.raises(ValueError):
        profiles.save_profile("ok-name", "")


def test_secrets_in_yaml_are_stripped_on_load(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = Path(str(tmp_path / "profiles.yml"))
    path.write_text(
        yaml.safe_dump({
            "active": "sneaky",
            "profiles": {
                "sneaky": {"model": "gpt-4o", "api_key": "sk-live-should-vanish"},
            },
        }),
        encoding="utf-8",
    )
    data = profiles.load_profiles_file()
    assert data["profiles"]["sneaky"] == {"model": "gpt-4o"}


def test_max_tokens_and_dotted_name_survive_second_save(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("work.v1", "gpt-4o", max_tokens=8000)
    profiles.save_profile("other", "ollama/llama3.2")
    data = profiles.load_profiles_file()
    assert data["profiles"]["work.v1"]["max_tokens"] == 8000
    raw = yaml.safe_load((tmp_path / "profiles.yml").read_text(encoding="utf-8"))
    assert raw["profiles"]["work.v1"]["max_tokens"] == 8000
    assert "other" in raw["profiles"]


def test_profile_name_containing_token_survives(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = Path(str(tmp_path / "profiles.yml"))
    path.write_text(
        yaml.safe_dump({
            "active": "my-token",
            "profiles": {
                "my-token": {"model": "gpt-4o", "max_tokens": 1234, "api_key": "nope"},
            },
        }),
        encoding="utf-8",
    )
    data = profiles.load_profiles_file()
    assert data["profiles"]["my-token"] == {"model": "gpt-4o", "max_tokens": 1234}


def test_load_config_applies_active_profile_when_no_project_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/qwen2.5-coder")
    config = load_config()
    assert config.model == "ollama/qwen2.5-coder"
    assert config.active_profile == "local"


def test_project_file_wins_over_user_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/qwen2.5-coder")
    (tmp_path / "occ.yml").write_text("model: gpt-4o\n", encoding="utf-8")
    config = load_config()
    assert config.model == "gpt-4o"
    # Active pointer is still recorded for doctor display.
    assert config.active_profile == "local"


def test_apply_profile_never_touches_keys():
    config = AgentConfig(model="gpt-4o", api_key="keep-me")
    profiles.apply_profile_to_config(config, {"model": "ollama/llama3.2", "api_key": "evil"})
    assert config.model == "ollama/llama3.2"
    assert config.api_key == "keep-me"


def test_apply_profile_replace_clears_leftover_base_url():
    config = AgentConfig(
        model="my-local",
        base_url="http://127.0.0.1:8000/v1",
        num_ctx=8192,
        max_tokens=32000,
    )
    profiles.apply_profile_to_config(
        config,
        {"model": "claude-sonnet-4-20250514"},
        replace=True,
    )
    assert config.model == "claude-sonnet-4-20250514"
    assert config.base_url is None
    assert config.num_ctx is None
    assert config.max_tokens == 16000


def test_apply_profile_merge_keeps_unset_keys():
    config = AgentConfig(model="gpt-4o", base_url="http://127.0.0.1:8000/v1")
    profiles.apply_profile_to_config(config, {"model": "claude-sonnet-4-20250514"})
    assert config.model == "claude-sonnet-4-20250514"
    assert config.base_url == "http://127.0.0.1:8000/v1"


def test_check_provider_auth_fails_fast_on_placeholder(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config = AgentConfig(model="groq/llama-3.3-70b-versatile", api_key="changeme")
    ok, summary, required = check_provider_auth(config, environ={})
    assert ok is False
    assert required == "GROQ_API_KEY"
    assert "placeholder" in summary


def test_check_provider_auth_ollama_needs_no_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ok, _summary, required = check_provider_auth(
        AgentConfig(model="ollama/llama3.2"), environ={}
    )
    assert ok is True
    assert required is None


def test_provider_save_does_not_write_occ_yml(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config = AgentConfig(model="ollama/llama3.2")
    out: list[str] = []
    code = run_provider_command(
        config,
        argparse.Namespace(task="save", provider_args=["local"], json=False),
        print_fn=out.append,
    )
    assert code == 0
    assert (tmp_path / "profiles.yml").is_file()
    assert not (tmp_path / "occ.yml").exists()
    assert config.active_profile == "local"


def test_provider_use_sets_active_without_touching_project(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("a", "ollama/llama3.2", make_active=False)
    profiles.save_profile("b", "ollama/qwen2.5-coder", make_active=False)
    config = AgentConfig(model="gpt-4o", base_url="http://127.0.0.1:8000/v1")
    out: list[str] = []
    code = run_provider_command(
        config,
        argparse.Namespace(task="use", provider_args=["b"], json=False),
        print_fn=out.append,
    )
    assert code == 0
    assert config.model == "ollama/qwen2.5-coder"
    assert config.base_url is None
    assert not (tmp_path / "occ.yml").exists()


def test_provider_use_warns_when_key_missing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("cloud", "groq/llama-3.3-70b-versatile", make_active=False)
    config = AgentConfig(model="ollama/llama3.2")
    out: list[str] = []
    code = run_provider_command(
        config,
        argparse.Namespace(task="use", provider_args=["cloud"], json=False),
        print_fn=out.append,
    )
    # CLI records the choice for next `occ` but fails fast so CI/scripts see it.
    assert code == 1
    assert config.model == "groq/llama-3.3-70b-versatile"
    assert "GROQ_API_KEY" in "\n".join(out)


def test_provider_list_json_shape(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/llama3.2")
    config = AgentConfig()
    out: list[str] = []
    code = run_provider_command(
        config,
        argparse.Namespace(task="list", provider_args=[], json=True),
        print_fn=out.append,
    )
    assert code == 0
    payload = json.loads(out[0])
    assert payload["profiles"]["local"]["model"] == "ollama/llama3.2"


def test_provider_delete_unknown_is_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out: list[str] = []
    code = run_provider_command(
        AgentConfig(),
        argparse.Namespace(task="delete", provider_args=["nope"], json=False),
        print_fn=out.append,
    )
    assert code == 1


def test_provider_wizard_saves_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    answers = iter(["6", "ollama/qwen2.5-coder", "", "local"])
    out: list[str] = []
    code = run_provider_command(
        AgentConfig(),
        argparse.Namespace(task="wizard", provider_args=[], json=False),
        print_fn=out.append,
        input_fn=lambda _prompt="": next(answers),
    )
    assert code == 0
    assert profiles.get_profile("local") is not None
    assert profiles.get_profile("local")["model"] == "ollama/qwen2.5-coder"


def test_fetch_remote_models_prefers_cache(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    cache_path = profiles._cache_path("openrouter", None)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"models": ["a/b", "c/d"]}), encoding="utf-8")
    models, source = profiles.fetch_remote_models("openrouter")
    assert source == "cache"
    assert models == ["a/b", "c/d"]


def test_doctor_reports_active_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/llama3.2")
    config = load_config()
    report = collect_doctor_report(
        config,
        environ={},
        which=lambda _name: None,
        ollama_probe=lambda _url: (False, "down"),
        config_path="",
        cwd=str(tmp_path),
    )
    payload = report.to_dict()
    assert payload["active_profile"] == "local"
    assert "profiles.yml" in (payload["profiles_path"] or "")
    assert any(item["id"] == "profile" for item in payload["checks"])


def test_switch_provider_in_session_ollama(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/qwen2.5-coder", make_active=False)
    config = AgentConfig(model="claude-sonnet-4-20250514")
    agent = MagicMock()
    agent._context_mgr = MagicMock()
    ok, message = switch_provider_in_session(config, agent, "local")
    assert ok is True
    assert "local" in message
    assert config.model == "ollama/qwen2.5-coder"
    assert agent.provider is not None


def test_switch_provider_unknown_and_missing_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config = AgentConfig(model="ollama/llama3.2")
    agent = MagicMock()
    ok, _message = switch_provider_in_session(config, agent, "nope")
    assert ok is False
    profiles.save_profile("cloud", "groq/llama-3.3-70b-versatile", make_active=False)
    ok, message = switch_provider_in_session(config, agent, "cloud")
    assert ok is False
    assert "GROQ_API_KEY" in message or "auth" in message.lower()


@pytest.mark.asyncio
async def test_provider_slash_list_save_use(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config, agent, mgr = _slash_env()
    config.model = "ollama/llama3.2"
    assert await handle_slash_command("/provider list", config, agent, mgr) == "handled"
    assert await handle_slash_command("/provider save local", config, agent, mgr) == "handled"
    assert profiles.get_profile("local") is not None
    config.model = "claude-sonnet-4-20250514"
    assert await handle_slash_command("/provider use local", config, agent, mgr) == "handled"
    assert config.model == "ollama/llama3.2"


@pytest.mark.asyncio
async def test_provider_slash_use_unknown_is_handled(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config, agent, mgr = _slash_env()
    assert await handle_slash_command("/provider use nope", config, agent, mgr) == "handled"
    assert await handle_slash_command("/provider bogus", config, agent, mgr) == "handled"


@pytest.mark.asyncio
async def test_provider_slash_show_named(tmp_path, monkeypatch, capsys):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/llama3.2")
    config, agent, mgr = _slash_env()
    assert await handle_slash_command("/provider show local", config, agent, mgr) == "handled"
    captured = capsys.readouterr().out
    assert "local:" in captured
    assert "ollama/llama3.2" in captured
    assert await handle_slash_command("/provider show nope", config, agent, mgr) == "handled"
    assert "Unknown profile" in capsys.readouterr().out


def test_occ_provider_argv_parses(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["occ", "provider", "list"])
    args = parse_args()
    assert args.command == "provider"
    assert args.task == "list"


def test_occ_profile_flag_selects_saved_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("local", "ollama/qwen2.5-coder", make_active=False)
    profiles.save_profile("other", "ollama/llama3.2", make_active=False)
    monkeypatch.setattr(sys, "argv", ["occ", "--profile", "local"])
    args = parse_args()
    config = resolve_config(args)
    assert config.model == "ollama/qwen2.5-coder"
    assert config.active_profile == "local"


def test_explicit_profile_clears_project_base_url(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("work", "claude-sonnet-4-20250514", make_active=False)
    (tmp_path / "occ.yml").write_text(
        "model: my-local\nbase_url: http://127.0.0.1:8000/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["occ", "--profile", "work"])
    config = resolve_config(parse_args())
    assert config.model == "claude-sonnet-4-20250514"
    assert config.base_url is None
    from open_claude_code.providers.registry import resolve_provider
    assert resolve_provider(config.model, config.base_url) == "anthropic"


def test_implicit_profile_loses_to_project_base_url(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.save_profile("work", "claude-sonnet-4-20250514")
    (tmp_path / "occ.yml").write_text(
        "model: my-local\nbase_url: http://127.0.0.1:8000/v1\n",
        encoding="utf-8",
    )
    config = load_config()
    assert config.model == "my-local"
    assert config.base_url == "http://127.0.0.1:8000/v1"
    assert config.active_profile == "work"


def test_occ_provider_models_refresh_parses(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["occ", "provider", "models", "groq", "--refresh"])
    args = parse_args()
    assert args.command == "provider"
    assert args.task == "models"
    assert args.provider_args == ["groq"]
    assert args.refresh is True


def test_occ_provider_save_no_activate_parses(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["occ", "provider", "save", "local", "--no-activate"])
    args = parse_args()
    assert args.task == "save"
    assert args.provider_args == ["local"]
    assert args.no_activate is True


def test_catalog_api_key_picks_provider_env(monkeypatch):
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    assert profiles.catalog_api_key("groq") == "gsk-test"
    assert profiles.catalog_api_key("groq", api_key="explicit") == "explicit"
    assert profiles.catalog_api_key("ollama") is None
    assert profiles.catalog_api_key("openrouter") is None


def test_fetch_remote_models_sends_groq_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"id": "llama-3.3-70b-versatile"}]}

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers or {}
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)
    models, source = profiles.fetch_remote_models("groq", use_cache=False)
    assert source == "live"
    assert models == ["llama-3.3-70b-versatile"]
    assert captured["headers"].get("Authorization") == "Bearer gsk-test"
