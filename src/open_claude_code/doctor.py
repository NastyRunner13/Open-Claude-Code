"""Runtime diagnostics for `occ doctor`.

Reports which API keys are set (never their values), which provider a model
string maps to, whether Ollama answers, and whether `rg` is on PATH. The JSON
shape is the persistable report CI can consume.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping

from open_claude_code import __version__
from open_claude_code.config import AgentConfig, find_config_path
from open_claude_code.providers.ollama import DEFAULT_BASE_URL, normalize_ollama_url
from open_claude_code.providers.registry import resolve_provider

KEY_ENV_VARS: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OPENAI_API_KEY", "openai"),
    ("GEMINI_API_KEY", "gemini"),
    ("GROQ_API_KEY", "groq"),
    ("OPENROUTER_API_KEY", "openrouter"),
)

REQUIRED_ENV: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-compat": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
}

_PLACEHOLDER_VALUES = frozenset({
    "changeme", "placeholder", "example", "xxx", "todo", "none", "null",
    "your-api-key", "your_api_key", "api-key-here", "sk-...",
})
DEFAULT_OLLAMA_URL = DEFAULT_BASE_URL


@dataclass
class DoctorCheck:
    id: str
    ok: bool
    severity: str  # error | warn | info
    summary: str
    detail: str = ""


@dataclass
class DoctorReport:
    version: str
    python: str
    cwd: str
    generated_at: str
    model: str
    provider: str
    config_path: str | None
    active_profile: str | None = None
    profiles_path: str | None = None
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.severity == "error")

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    if lowered in _PLACEHOLDER_VALUES:
        return True
    if lowered.startswith("your-") or lowered.startswith("your_"):
        return True
    return "<your" in lowered or "replace-me" in lowered


def _env_value(environ: Mapping[str, str], name: str) -> str:
    return str(environ.get(name, "") or "")


def _ollama_base_url(
    config: AgentConfig,
    provider: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    if provider == "ollama" and config.base_url:
        return normalize_ollama_url(config.base_url)
    if environ is not None:
        host = str(environ.get("OLLAMA_HOST") or "").strip()
        return normalize_ollama_url(host or DEFAULT_OLLAMA_URL)
    return normalize_ollama_url(None)


def probe_ollama(base_url: str = DEFAULT_OLLAMA_URL, timeout: float = 1.5) -> tuple[bool, str]:
    """Hit Ollama's native `/api/version`, then the OpenAI `/v1/models` shim."""
    url = normalize_ollama_url(base_url)
    try:
        import httpx
    except ImportError:
        return False, "httpx is not installed"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(f"{url}/api/version")
            if response.status_code == 200:
                try:
                    version = response.json().get("version", "")
                except ValueError:
                    version = ""
                return True, version or "reachable"
            models = client.get(f"{url}/v1/models")
            if models.status_code == 200:
                return True, "OpenAI-compat /v1/models reachable"
            return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


def collect_doctor_report(
    config: AgentConfig,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    ollama_probe: Callable[[str], tuple[bool, str]] | None = None,
    python_version: tuple[int, ...] | None = None,
    now: datetime | None = None,
    cwd: str | Path | None = None,
    config_path: str | Path | None = None,
) -> DoctorReport:
    """Build a doctor report. Network I/O is confined to the Ollama probe."""
    environ = environ if environ is not None else os.environ
    py = python_version or sys.version_info[:3]
    generated = (now or datetime.now(UTC)).isoformat()
    workdir = str(Path(cwd or Path.cwd()).resolve())
    found_config = config_path if config_path is not None else find_config_path()
    provider = resolve_provider(config.model, config.base_url)
    checks: list[DoctorCheck] = []

    py_ok = py >= (3, 12)
    checks.append(
        DoctorCheck(
            id="python",
            ok=py_ok,
            severity="error",
            summary=".".join(str(part) for part in py),
            detail="OCC requires Python 3.12+",
        )
    )
    checks.append(
        DoctorCheck(
            id="occ_version",
            ok=True,
            severity="info",
            summary=__version__,
        )
    )

    config_ok = found_config is not None
    checks.append(
        DoctorCheck(
            id="config",
            ok=True,
            severity="info" if config_ok else "warn",
            summary=str(found_config) if config_ok else "no occ.yml (using defaults)",
        )
    )
    checks.append(
        DoctorCheck(
            id="provider",
            ok=True,
            severity="info",
            summary=f"{config.model} -> {provider}",
            detail=f"base_url={config.base_url}" if config.base_url else "",
        )
    )

    required = REQUIRED_ENV.get(provider)
    cli_key = (config.api_key or "").strip()
    cli_placeholder = bool(cli_key) and _is_placeholder(cli_key)
    if required is None:
        auth_ok, auth_summary, auth_detail = True, "no API key required", ""
    elif cli_key and not cli_placeholder:
        auth_ok, auth_summary, auth_detail = True, "api_key supplied via CLI/config", required
    elif cli_placeholder:
        auth_ok, auth_summary, auth_detail = False, "api_key looks like a placeholder", required
    else:
        env_val = _env_value(environ, required)
        if not env_val.strip():
            auth_ok, auth_summary, auth_detail = (
                False,
                f"{required} is not set",
                f"export {required} or pass --api-key",
            )
        elif _is_placeholder(env_val):
            auth_ok, auth_summary, auth_detail = False, f"{required} looks like a placeholder", ""
        else:
            auth_ok, auth_summary, auth_detail = True, f"{required} is set", ""
    checks.append(
        DoctorCheck(
            id="provider_auth",
            ok=auth_ok,
            severity="error",
            summary=auth_summary,
            detail=auth_detail,
        )
    )

    for env_name, _kind in KEY_ENV_VARS:
        raw = _env_value(environ, env_name)
        present = bool(raw.strip())
        placeholder = present and _is_placeholder(raw)
        if placeholder:
            checks.append(
                DoctorCheck(
                    id=f"env.{env_name}",
                    ok=False,
                    severity="warn",
                    summary="placeholder",
                )
            )
        elif present:
            checks.append(
                DoctorCheck(
                    id=f"env.{env_name}",
                    ok=True,
                    severity="info",
                    summary="set",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    id=f"env.{env_name}",
                    ok=True,
                    severity="info",
                    summary="not set",
                )
            )

    ollama_url = _ollama_base_url(config, provider, environ)
    probe = ollama_probe or probe_ollama
    ollama_ok, ollama_detail = probe(ollama_url)
    ollama_required = provider == "ollama"
    if ollama_required:
        ollama_severity = "error"
        ollama_check_ok = ollama_ok
    else:
        ollama_severity = "info" if ollama_ok else "warn"
        ollama_check_ok = True
    checks.append(
        DoctorCheck(
            id="ollama",
            ok=ollama_check_ok,
            severity=ollama_severity,
            summary="reachable" if ollama_ok else "unreachable",
            detail=f"{ollama_url}: {ollama_detail}",
        )
    )

    rg_path = which("rg")
    checks.append(
        DoctorCheck(
            id="ripgrep",
            ok=True,
            severity="info" if rg_path else "warn",
            summary=rg_path or "not on PATH (Python grep fallback)",
        )
    )

    try:
        from open_claude_code import profiles as _profiles

        _profile_data = _profiles.load_profiles_file()
        _active = config.active_profile or _profile_data.get("active")
        _profiles_path = str(_profile_data.get("path") or _profiles.get_profiles_path())
        _saved = _profile_data.get("profiles", {})
    except Exception:
        _active, _profiles_path, _saved = config.active_profile, None, {}
    if _active and isinstance(_saved, dict) and _active in _saved:
        _entry = _saved[_active]
        checks.append(
            DoctorCheck(
                id="profile",
                ok=True,
                severity="info",
                summary=f"{_active}: {str(_entry.get('model', ''))}",
                detail=str(_profiles_path or ""),
            )
        )
    elif _active:
        checks.append(
            DoctorCheck(
                id="profile",
                ok=True,
                severity="warn",
                summary=f"{_active} (not in {_profiles_path})",
                detail="profile name set but no matching saved entry",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                id="profile",
                ok=True,
                severity="info",
                summary="no saved profile (using occ.yml/defaults)",
                detail=str(_profiles_path or ""),
            )
        )

    return DoctorReport(
        version=__version__,
        python=".".join(str(part) for part in py),
        cwd=workdir,
        generated_at=generated,
        model=config.model,
        provider=provider,
        config_path=str(found_config) if found_config else None,
        active_profile=_active,
        profiles_path=_profiles_path,
        checks=checks,
    )


def run_doctor_cli(
    config: AgentConfig,
    *,
    json_output: bool = False,
    report_path: str | Path | None = None,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Print a doctor report, optionally persist JSON, and return a process exit code."""
    report = collect_doctor_report(config)
    payload = report.to_dict()
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if report_path is not None:
        destination = Path(report_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded, encoding="utf-8")
    if json_output:
        print_fn(encoded.rstrip("\n"))
    else:
        print_fn(_format_human(report, saved_to=report_path))
    return 0 if report.ok else 1


def _format_human(report: DoctorReport, saved_to: str | Path | None = None) -> str:
    status = "ok" if report.ok else "failed"
    lines = [
        f"OCC doctor {report.version}  [{status}]",
        f"  python    {report.python}",
        f"  cwd       {report.cwd}",
        f"  model     {report.model} -> {report.provider}",
        f"  config    {report.config_path or '(defaults)'}",
        f"  profile   {report.active_profile or '(none)'}"
        + (f"  [{report.profiles_path}]" if report.profiles_path else ""),
        "",
    ]
    for check in report.checks:
        if not check.ok:
            mark = "FAIL"
        elif check.severity == "warn":
            mark = "warn"
        else:
            mark = "ok"
        extra = f"  {check.detail}" if check.detail else ""
        lines.append(f"  [{mark:<4}] {check.id:<22} {check.summary}{extra}")
    if saved_to is not None:
        lines.append("")
        lines.append(f"  report written to {saved_to}")
    return "\n".join(lines)
