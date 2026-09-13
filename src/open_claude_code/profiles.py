"""User-level provider profiles for `/provider` and `occ provider`.

A profile is a small YAML stanza that remembers *which* provider path works
(``model`` + optional ``base_url`` / ``num_ctx`` / ``max_tokens``). Profiles
live outside the project so switching providers mid-session never rewrites
``occ.yml`` unless the user asks.

File layout (``~/.occ/profiles.yml``)::

    active: work-default
    profiles:
      work-default:
        model: openrouter/anthropic/claude-sonnet-4
      local:
        model: ollama/qwen2.5-coder
        num_ctx: 32768

Secrets are never persisted here. ``save_profile()`` refuses ``api_key`` and
friends; keys come from the environment (``ANTHROPIC_API_KEY``,
``OPENROUTER_API_KEY``, …) or ``--api-key``. Session snapshots already redact
credential-looking keys, so the JSONL ledger stays clean.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALLOWED_KEYS = ("model", "base_url", "num_ctx", "max_tokens")
_SECRET_KEYS = frozenset({"api_key", "authorization", "credential", "password", "secret", "token"})
_SECRET_SUFFIXES = ("_api_key", "_authorization", "_credential", "_password", "_secret", "_token")
_DEFAULT_MAX_TOKENS = 16000  # SYNC: AgentConfig.max_tokens
# SYNC: doctor.REQUIRED_ENV (catalog hosts only)
_CATALOG_ENV = {
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai-compat": "OPENAI_API_KEY",
}

# Provider setup hints shown by `/provider` and `occ provider wizard`.
# Keep this as data, not a new provider SDK: OpenRouter or `--base-url`
# covers every partner gateway.
PROVIDER_GUIDE: dict[str, dict[str, str]] = {
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "examples": "claude-sonnet-4-20250514",
        "notes": "Default. Set ANTHROPIC_API_KEY.",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "examples": "gpt-4o",
        "notes": "Set OPENAI_API_KEY.",
    },
    "gemini": {
        "env": "GEMINI_API_KEY",
        "examples": "gemini-2.0-flash",
        "notes": "Set GEMINI_API_KEY (google-genai extra).",
    },
    "groq": {
        "env": "GROQ_API_KEY",
        "examples": "groq/llama-3.3-70b-versatile",
        "notes": "The groq/ prefix is required.",
    },
    "openrouter": {
        "env": "OPENROUTER_API_KEY",
        "examples": "openrouter/anthropic/claude-sonnet-4",
        "notes": "Any catalog id; vendor/model also routes here when the key is set.",
    },
    "ollama": {
        "env": "",
        "examples": "ollama/qwen2.5-coder",
        "notes": "No key. Needs `ollama serve` + `ollama pull <model>`.",
    },
    "openai-compat": {
        "env": "OPENAI_API_KEY",
        "examples": "my-model --base-url https://host/v1",
        "notes": "Any OpenAI-compatible host (vLLM, LM Studio, Together).",
    },
}

_MODEL_CACHE_TTL_SECONDS = 24 * 3600


@dataclass
class ProviderProfile:
    """Validated, secret-free provider settings."""

    name: str
    model: str
    base_url: str | None = None
    num_ctx: int | None = None
    max_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model}
        if self.base_url:
            payload["base_url"] = self.base_url
        if self.num_ctx is not None:
            payload["num_ctx"] = self.num_ctx
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        return payload


def get_profiles_path(path: str | Path | None = None) -> Path:
    """Return the user-level profiles file. ``OCC_PROFILES_PATH`` wins (tests)."""
    override = os.environ.get("OCC_PROFILES_PATH", "").strip()
    if path is not None:
        return Path(path).expanduser()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".occ" / "profiles.yml"


def get_models_cache_dir() -> Path:
    override = os.environ.get("OCC_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".occ" / "cache"


def validate_profile_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ValueError("profile name cannot be empty")
    if not _NAME_RE.match(clean):
        raise ValueError(
            "profile name must start alphanumeric and contain only "
            "letters, digits, dot, dash, underscore (max 64 chars)"
        )
    return clean


def _clean_settings(
    model: str,
    base_url: str | None = None,
    num_ctx: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    cleaned_model = (model or "").strip()
    if not cleaned_model:
        raise ValueError("profile model cannot be empty")
    payload: dict[str, Any] = {"model": cleaned_model}
    if base_url is not None and str(base_url).strip():
        payload["base_url"] = str(base_url).strip()
    if num_ctx is not None:
        try:
            payload["num_ctx"] = max(1, int(num_ctx))
        except (TypeError, ValueError) as exc:
            raise ValueError("num_ctx must be an integer") from exc
    if max_tokens is not None:
        try:
            payload["max_tokens"] = max(1, int(max_tokens))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_tokens must be an integer") from exc
    return payload


def _is_secret_key(name: str) -> bool:
    lowered = str(name).lower()
    return lowered in _SECRET_KEYS or lowered.endswith(_SECRET_SUFFIXES)


def _strip_secrets(raw: Any) -> Any:
    """Drop credential-looking keys from a profile stanza. Match whole names, not substrings."""
    if isinstance(raw, dict):
        return {
            str(key): _strip_secrets(value)
            for key, value in raw.items()
            if not _is_secret_key(str(key))
        }
    if isinstance(raw, list):
        return [_strip_secrets(item) for item in raw]
    return raw


def _read_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    # Strip secrets inside stanzas only; profile names are not field names.
    profiles = raw.get("profiles")
    if isinstance(profiles, dict):
        raw = dict(raw)
        raw["profiles"] = {
            name: _strip_secrets(settings) if isinstance(settings, dict) else settings
            for name, settings in profiles.items()
        }
    return raw


def load_profiles_file(path: str | Path | None = None) -> dict[str, Any]:
    """Return ``{"active": str|None, "profiles": {name: settings}}`` (never raises)."""
    resolved = get_profiles_path(path)
    raw = _read_file(resolved)
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        return {"active": None, "profiles": {}, "path": str(resolved)}
    cleaned: dict[str, dict[str, Any]] = {}
    for name, settings in profiles.items():
        if not isinstance(name, str) or not _NAME_RE.match(name.strip()):
            continue
        if not isinstance(settings, dict):
            continue
        model = settings.get("model")
        if not isinstance(model, str) or not model.strip():
            continue
        entry: dict[str, Any] = {"model": model.strip()}
        for key in _ALLOWED_KEYS:
            if key == "model" or key not in settings:
                continue
            value = settings[key]
            if key == "base_url":
                if isinstance(value, str) and value.strip():
                    entry[key] = value.strip()
                continue
            if value is None:
                continue
            try:
                entry[key] = max(1, int(value))
            except (TypeError, ValueError):
                continue
        cleaned[name.strip()] = entry
    active = raw.get("active")
    active_name = active.strip() if isinstance(active, str) and active.strip() else None
    if active_name is not None and active_name not in cleaned:
        active_name = None
    return {"active": active_name, "profiles": cleaned, "path": str(resolved)}


def list_profiles(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    return dict(load_profiles_file(path).get("profiles", {}))


def get_profile(name: str, path: str | Path | None = None) -> dict[str, Any] | None:
    profiles = list_profiles(path)
    return profiles.get((name or "").strip())


def get_active_profile(
    path: str | Path | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    data = load_profiles_file(path)
    active = data.get("active")
    if not isinstance(active, str):
        return None, None
    settings = data.get("profiles", {}).get(active)
    return (active, dict(settings) if isinstance(settings, dict) else None)


def _write_file(resolved: Path, payload: dict[str, Any]) -> None:
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp" if resolved.suffix else ".tmp")
    tmp.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    tmp.replace(resolved)


def save_profile(
    name: str,
    model: str,
    *,
    base_url: str | None = None,
    num_ctx: int | None = None,
    max_tokens: int | None = None,
    make_active: bool = True,
    path: str | Path | None = None,
) -> ProviderProfile:
    """Persist a secret-free profile and return it. Never writes ``occ.yml``."""
    clean_name = validate_profile_name(name)
    settings = _clean_settings(model, base_url, num_ctx, max_tokens)
    resolved = get_profiles_path(path)
    data = load_profiles_file(resolved)
    profiles = data.get("profiles", {})
    profiles[clean_name] = settings
    payload: dict[str, Any] = {
        "active": clean_name if make_active else data.get("active"),
        "profiles": profiles,
    }
    if payload["active"] is not None and payload["active"] not in profiles:
        payload["active"] = clean_name if make_active else None
    _write_file(resolved, payload)
    return ProviderProfile(name=clean_name, **settings)  # type: ignore[arg-type]


def delete_profile(name: str, path: str | Path | None = None) -> bool:
    clean = (name or "").strip()
    resolved = get_profiles_path(path)
    data = load_profiles_file(resolved)
    profiles = data.get("profiles", {})
    if clean not in profiles:
        return False
    del profiles[clean]
    active = data.get("active")
    payload: dict[str, Any] = {
        "active": None if active == clean else active,
        "profiles": profiles,
    }
    _write_file(resolved, payload)
    return True


def set_active_profile(name: str, path: str | Path | None = None) -> dict[str, Any]:
    clean = (name or "").strip()
    resolved = get_profiles_path(path)
    data = load_profiles_file(resolved)
    profiles = data.get("profiles", {})
    if clean not in profiles:
        known = ", ".join(sorted(profiles)) or "(no profiles saved)"
        raise ValueError(f"unknown profile '{clean}'. Known: {known}")
    _write_file(resolved, {"active": clean, "profiles": profiles})
    return dict(profiles[clean])


def apply_profile_to_config(
    config: Any,
    settings: dict[str, Any] | None,
    *,
    replace: bool = False,
) -> Any:
    """Copy profile settings onto an AgentConfig. Never touches keys or files.

    replace=True overwrites the provider tuple so an explicit ``--profile`` /
    ``use`` cannot inherit a leftover project ``base_url``. replace=False
    merges, so project ``occ.yml`` still wins for keys it sets.
    """
    if not settings:
        return config
    if isinstance(settings.get("model"), str) and settings["model"].strip():
        config.model = settings["model"].strip()
    if replace or "base_url" in settings:
        url = settings.get("base_url")
        config.base_url = str(url).strip() if isinstance(url, str) and str(url).strip() else None
    if replace or settings.get("num_ctx") is not None:
        value = settings.get("num_ctx")
        if value is None:
            config.num_ctx = None
        else:
            try:
                config.num_ctx = max(1, int(value))
            except (TypeError, ValueError):
                if replace:
                    config.num_ctx = None
    if replace or settings.get("max_tokens") is not None:
        value = settings.get("max_tokens")
        if value is None:
            config.max_tokens = _DEFAULT_MAX_TOKENS
        else:
            try:
                config.max_tokens = max(1, int(value))
            except (TypeError, ValueError):
                if replace:
                    config.max_tokens = _DEFAULT_MAX_TOKENS
    return config


def describe_profile(name: str, settings: dict[str, Any]) -> str:
    bits = [str(settings.get("model", ""))]
    if settings.get("base_url"):
        bits.append(str(settings["base_url"]))
    extras = []
    if settings.get("num_ctx") is not None:
        extras.append(f"num_ctx={settings['num_ctx']}")
    if settings.get("max_tokens") is not None:
        extras.append(f"max_tokens={settings['max_tokens']}")
    if extras:
        bits.append("(" + ", ".join(extras) + ")")
    return f"{name}: {' '.join(bits)}".strip()


def _cache_path(provider: str, base_url: str | None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}-{base_url or 'default'}")[:120]
    return get_models_cache_dir() / f"models-{safe}.json"


def _read_model_cache(cache_path: Path) -> list[str] | None:
    try:
        if not cache_path.is_file():
            return None
        if time.time() - cache_path.stat().st_mtime > _MODEL_CACHE_TTL_SECONDS:
            return None
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if isinstance(models, list) and all(isinstance(item, str) for item in models):
        return [item for item in models if item.strip()][:500]
    return None


def _write_model_cache(cache_path: Path, models: list[str]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"models": models[:500]}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(cache_path)
    except OSError:
        pass


def catalog_api_key(provider: str, api_key: str | None = None) -> str | None:
    """Key for a live /models fetch. Explicit ``api_key`` wins; else the provider env var."""
    explicit = (api_key or "").strip()
    if explicit:
        return explicit
    env_name = _CATALOG_ENV.get((provider or "").strip().lower())
    if not env_name:
        return None
    return (os.environ.get(env_name) or "").strip() or None


def fetch_remote_models(
    provider: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 6.0,
    use_cache: bool = True,
) -> tuple[list[str], str]:
    """Best-effort live model catalog. Returns ``(models, source)``; never raises.

    Sources: ``cache`` | ``live`` | ``unavailable:<reason>``. Ollama reads
    ``/api/tags``; OpenRouter and OpenAI-compat hosts read ``/v1/models``.
    Anthropic/Gemini have no listable catalog from OCC, so they report
    ``unavailable`` instead of guessing.
    """
    normalized = (provider or "").strip().lower()
    cache_path = _cache_path(normalized, base_url)
    if use_cache:
        cached = _read_model_cache(cache_path)
        if cached is not None:
            return cached, "cache"

    try:
        import httpx
    except ImportError:
        return [], "unavailable:httpx is not installed"

    url: str | None = None
    headers: dict[str, str] = {}
    key = catalog_api_key(normalized, api_key)
    if normalized == "ollama":
        from open_claude_code.providers.ollama import normalize_ollama_url

        url = f"{normalize_ollama_url(base_url)}/api/tags"
    elif normalized == "openrouter":
        url = "https://openrouter.ai/api/v1/models"
        if key:
            headers["Authorization"] = f"Bearer {key}"
    elif normalized in {"openai", "openai-compat", "groq"}:
        if normalized == "groq":
            url = "https://api.groq.com/openai/v1/models"
        elif base_url:
            url = f"{str(base_url).rstrip('/')}/models"
        else:
            url = "https://api.openai.com/v1/models"
        if key:
            headers["Authorization"] = f"Bearer {key}"
    else:
        return [], f"unavailable:no listable catalog for '{normalized or 'unknown'}'"

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers=headers or None)
    except Exception as exc:
        return [], f"unavailable:{exc}"
    if response.status_code >= 400:
        return [], f"unavailable:HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return [], "unavailable:invalid JSON"
    models: list[str] = []
    if normalized == "ollama":
        items = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    models.append(str(item["name"]))
    else:
        items = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    models.append(str(item["id"]))
    models = [item for item in models if item.strip()][:500]
    if not models:
        return [], "unavailable:empty catalog"
    _write_model_cache(cache_path, models)
    return models, "live"
