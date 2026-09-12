"""occ doctor report: keys, provider mapping, ollama, ripgrep, JSON shape."""

from __future__ import annotations

import json
from pathlib import Path

from open_claude_code.config import AgentConfig
from open_claude_code.doctor import collect_doctor_report, run_doctor_cli
from open_claude_code.providers.registry import resolve_provider


def _report(config: AgentConfig, **kwargs):
    kwargs.setdefault("environ", {})
    kwargs.setdefault("which", lambda _name: None)
    kwargs.setdefault("ollama_probe", lambda _url: (False, "down"))
    kwargs.setdefault("config_path", "")
    kwargs.setdefault("cwd", ".")
    return collect_doctor_report(config, **kwargs)


def _check(report, check_id: str):
    return next(item for item in report.checks if item.id == check_id)


def test_resolve_provider_does_not_need_keys(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert resolve_provider("openrouter/anthropic/claude-sonnet-4") == "openrouter"
    assert resolve_provider("groq/llama-3.3-70b-versatile") == "groq"
    assert resolve_provider("ollama/llama3.2") == "ollama"
    assert resolve_provider("gpt-4o") == "openai"
    assert resolve_provider("claude-sonnet-4") == "anthropic"
    assert resolve_provider("mystery", base_url="http://localhost:8000/v1") == "openai-compat"


def test_missing_required_key_fails():
    report = _report(AgentConfig(model="claude-sonnet-4-20250514"))
    assert report.ok is False
    assert report.provider == "anthropic"
    assert _check(report, "provider_auth").ok is False
    assert "ANTHROPIC_API_KEY" in _check(report, "provider_auth").summary


def test_cli_api_key_satisfies_auth():
    report = _report(AgentConfig(model="gpt-4o", api_key="sk-test-live-key"))
    assert report.ok is True
    assert report.provider == "openai"
    assert _check(report, "provider_auth").ok is True


def test_unrelated_keys_do_not_fail_ci():
    report = _report(
        AgentConfig(model="claude-sonnet-4", api_key="sk-ant-live"),
        environ={"GROQ_API_KEY": "", "OPENAI_API_KEY": ""},
    )
    assert report.ok is True
    assert _check(report, "env.GROQ_API_KEY").ok is True
    assert _check(report, "env.GROQ_API_KEY").summary == "not set"


def test_placeholder_key_fails_for_mapped_provider():
    report = _report(AgentConfig(model="groq/llama-3.3-70b-versatile", api_key="changeme"))
    assert report.ok is False
    assert "placeholder" in _check(report, "provider_auth").summary


def test_ollama_unreachable_is_error_when_selected():
    report = _report(AgentConfig(model="ollama/llama3.2"))
    assert report.ok is False
    assert _check(report, "ollama").ok is False
    assert _check(report, "ollama").severity == "error"


def test_ollama_unreachable_is_warn_when_not_selected():
    report = _report(AgentConfig(model="claude-sonnet-4", api_key="sk-ant-live"))
    assert report.ok is True
    ollama = _check(report, "ollama")
    assert ollama.ok is True
    assert ollama.severity == "warn"
    assert ollama.summary == "unreachable"


def test_ripgrep_and_json_shape(tmp_path):
    report = _report(
        AgentConfig(model="claude-sonnet-4", api_key="sk-ant-live"),
        which=lambda name: str(tmp_path / "rg.exe") if name == "rg" else None,
        ollama_probe=lambda url: (True, "0.9"),
        cwd=tmp_path,
    )
    payload = report.to_dict()
    assert payload["ok"] is True
    assert payload["provider"] == "anthropic"
    assert payload["model"] == "claude-sonnet-4"
    assert "checks" in payload
    assert {item["id"] for item in payload["checks"]} >= {
        "python",
        "provider",
        "provider_auth",
        "env.ANTHROPIC_API_KEY",
        "ollama",
        "ripgrep",
    }
    assert _check(report, "ripgrep").summary.endswith("rg.exe")
    assert _check(report, "ollama").summary == "reachable"
    json.dumps(payload)


def test_python_too_old_fails():
    report = _report(
        AgentConfig(model="claude-sonnet-4", api_key="sk-ant-live"),
        python_version=(3, 11, 9),
    )
    assert report.ok is False
    assert _check(report, "python").ok is False


def test_run_doctor_cli_writes_report(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-from-env")
    printed: list[str] = []
    destination = tmp_path / "out" / "doctor.json"
    code = run_doctor_cli(
        AgentConfig(model="claude-sonnet-4"),
        json_output=True,
        report_path=destination,
        print_fn=printed.append,
    )
    assert destination.is_file()
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert "checks" in payload
    assert printed and json.loads(printed[0])["provider"] == "anthropic"
    assert code in {0, 1}


def test_openrouter_vendor_model_with_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert resolve_provider("anthropic/claude-sonnet-4") == "openrouter"
