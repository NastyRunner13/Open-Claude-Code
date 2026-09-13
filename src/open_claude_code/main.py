"""CLI entry point — wires up the agent with middleware and runs the REPL."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prompt_toolkit import PromptSession, HTML

from open_claude_code import __version__
from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig, load_config, save_config
from open_claude_code.cost import render_cost_report
from open_claude_code.doctor import run_doctor_cli
from open_claude_code.events import (
    EventBus, Error, PostToolUse, PreToolUse, Stop, Thinking, ToolDenied,
    TokenDelta, ToolCallDelta, UsageUpdated, ProviderFailure,
)
from open_claude_code.listeners import (
    register_approval_listener,
    register_logging_listeners,
    register_ui_listeners,
)
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.middleware.mcp import MCPMiddleware
from open_claude_code.middleware.memory import MemoryMiddleware
from open_claude_code.middleware.hooks import HooksMiddleware
from open_claude_code.middleware.plugins import PluginMiddleware
from open_claude_code.middleware.skills import SkillsMiddleware
from open_claude_code.modes import run_mode
from open_claude_code.planning import PlanningMiddleware
from open_claude_code.providers import ProviderError, create_provider
from open_claude_code.providers.registry import resolve_provider
from open_claude_code.sessions import SessionStore
from open_claude_code.subagents import AgentRegistry, PersonaRegistry
from open_claude_code.system_prompt import MODE_PROMPTS
from open_claude_code.tools import get_tools

console = Console()


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Open Claude Code — an open-source AI coding agent",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file (default: auto-detect occ.yml)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use (overrides config file)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Max tokens for model response (overrides config file)",
    )
    parser.add_argument(
        "--mode",
        choices=["ask", "plan", "agent"],
        default=None,
        help="Interaction mode: ask (no tools), plan (plan then execute), agent (full auto)",
    )
    parser.add_argument(
        "--skip-approval",
        action="store_true",
        default=None,
        help="Auto-approve all tool calls (skip y/n prompts)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the model provider (overrides env vars)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Custom API base URL (OpenAI-compatible endpoints: vLLM, Together, etc.)",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="SESSION_ID",
        help="Resume a durable session from .occ/sessions",
    )
    parser.add_argument("--version", action="version", version=f"Open Claude Code {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON output: exec lifecycle events, or the occ doctor report.",
    )
    parser.add_argument(
        "--max-budget",
        type=float,
        default=None,
        metavar="USD",
        help="Stop the agent when known session cost reaches this USD amount.",
    )
    parser.add_argument(
        "--report",
        default=None,
        metavar="PATH",
        help="Write the occ doctor JSON report to PATH.",
    )
    parser.add_argument("--output-last-message", metavar="PATH", help="Write the final assistant message to PATH (exec mode).")
    parser.add_argument("--output-schema", metavar="PATH", help="Validate the final exec message against a JSON schema subset.")
    parser.add_argument("--ephemeral", action="store_true", help="Do not write session or snapshot artifacts for this run.")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-final exec progress output.")
    parser.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "full-access"],
        help="Runtime capability sandbox; policy denials cannot be bypassed by approval flags.",
    )
    parser.add_argument(
        "--approval-mode",
        choices=["suggest", "auto", "full-access"],
        help="Exec approval mode: deny privileged calls, auto-approve permitted calls, or full access.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="Use a saved provider profile from ~/.occ/profiles.yml (overrides the active profile).",
    )
    parser.add_argument(
        "--refresh",
        "--no-cache",
        action="store_true",
        dest="refresh",
        help="Bust the cached /models catalog (`occ provider models`).",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Save a profile without making it the default (`occ provider save`).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["exec", "doctor", "provider"],
        help="exec runs a non-interactive task; doctor reports environment health; provider manages saved provider profiles.",
    )
    parser.add_argument("task", nargs="?", help="Task text for `occ exec`, or subcommand for `occ provider` (list|show|save|use|delete|wizard|models).")
    parser.add_argument(
        "provider_args",
        nargs="*",
        help="Extra arguments for `occ provider` (e.g. profile name).",
    )
    args = parser.parse_args()
    extra = list(args.provider_args or [])
    if args.command == "exec" and not args.task:
        parser.error("occ exec requires a task argument")
    if args.command == "exec" and extra:
        parser.error("unrecognized arguments: " + " ".join(extra))
    if args.command == "doctor" and (args.task or extra):
        bits = [item for item in (args.task, *extra) if item]
        parser.error("unrecognized arguments: " + " ".join(bits))
    if args.command is None and extra:
        parser.error("unrecognized arguments: " + " ".join(extra))
    return args


def resolve_config(args: argparse.Namespace) -> AgentConfig:
    """Merge config file, env vars, and CLI flags into final config."""
    config = load_config(args.config)

    # Saved provider profile: explicit --profile (or OCC_PROFILE) wins over
    # the active pointer stored in ~/.occ/profiles.yml. Project occ.yml
    # values loaded above still win unless the profile is explicitly asked
    # for — a checked-in config is never silently overridden.
    requested_profile = getattr(args, "profile", None) or os.environ.get("OCC_PROFILE", "").strip() or None
    if requested_profile:
        from open_claude_code import profiles as _profiles

        settings = _profiles.get_profile(requested_profile)
        if settings is None:
            raise SystemExit(f"unknown provider profile '{requested_profile}' (see `occ provider list`)")
        _profiles.apply_profile_to_config(config, settings, replace=True)
        config.active_profile = requested_profile.strip()

    # CLI and env overrides
    if args.model:
        config.model = args.model
    elif env_model := os.environ.get("OCC_MODEL"):
        config.model = env_model

    if args.max_tokens is not None:
        config.max_tokens = args.max_tokens

    if args.mode:
        config.mode = args.mode

    if args.skip_approval:
        config.skip_approval = True

    if args.api_key:
        config.api_key = args.api_key

    if args.base_url:
        config.base_url = args.base_url

    env_ctx = os.environ.get("OCC_OLLAMA_NUM_CTX", "").strip()
    if env_ctx:
        try:
            config.num_ctx = int(env_ctx)
        except ValueError:
            pass

    if args.ephemeral:
        config.persist_sessions = False
        config.persist_snapshots = False
    if args.sandbox:
        config.permission_mode = args.sandbox
        config.shell_policy = args.sandbox
    if args.approval_mode == "auto":
        config.skip_approval = True
    elif args.approval_mode == "full-access":
        config.skip_approval = True
        config.permission_mode = "full-access"
        config.shell_policy = "full-access"

    if args.max_budget is not None:
        config.max_budget_usd = args.max_budget

    return config


def check_provider_auth(
    config: AgentConfig,
    *,
    environ: dict[str, str] | None = None,
) -> tuple[bool, str, str | None]:
    """Fail-fast auth check for the effective model. No network, no secrets."""
    from open_claude_code.doctor import REQUIRED_ENV, _is_placeholder

    env = environ if environ is not None else os.environ
    provider = resolve_provider(config.model, config.base_url)
    required = REQUIRED_ENV.get(provider)
    if required is None:
        return True, "no API key required", None
    cli_key = (config.api_key or "").strip()
    if cli_key and not _is_placeholder(cli_key):
        return True, "api_key supplied via CLI/config", required
    if cli_key and _is_placeholder(cli_key):
        return False, "api_key looks like a placeholder", required
    env_val = str(env.get(required, "") or "")
    if not env_val.strip():
        return False, f"{required} is not set", required
    if _is_placeholder(env_val):
        return False, f"{required} looks like a placeholder", required
    return True, f"{required} is set", required


def run_provider_command(
    config: AgentConfig,
    args: argparse.Namespace,
    *,
    print_fn: object = None,
    input_fn: object = None,
) -> int:
    """Implement `occ provider ...`. Never writes project occ.yml or secrets."""
    from open_claude_code import profiles as _profiles

    out = print_fn if callable(print_fn) else print
    ask = input_fn if callable(input_fn) else input
    sub = (getattr(args, "task", None) or "").strip().lower()
    extra = list(getattr(args, "provider_args", None) or [])
    as_json = bool(getattr(args, "json", False))
    flags = {item for item in extra if item.startswith("--")}
    positionals = [item for item in extra if not item.startswith("--")]
    refresh = bool(getattr(args, "refresh", False)) or "--refresh" in flags or "--no-cache" in flags
    no_activate = bool(getattr(args, "no_activate", False)) or "--no-activate" in flags

    def emit(payload: object) -> None:
        out(json.dumps(payload, indent=2, sort_keys=True))

    if sub in {"", "show", "status"} and not positionals:
        data = _profiles.load_profiles_file()
        provider = resolve_provider(config.model, config.base_url)
        auth_ok, auth_summary, _required = check_provider_auth(config)
        if as_json:
            emit({
                "model": config.model,
                "provider": provider,
                "base_url": config.base_url,
                "active_profile": config.active_profile or data.get("active"),
                "profiles_path": data.get("path"),
                "auth_ok": auth_ok,
                "auth": auth_summary,
            })
            return 0
        out(f"  Model: {config.model} -> {provider}")
        if config.base_url:
            out(f"  Base URL: {config.base_url}")
        active = config.active_profile or data.get("active")
        out(f"  Profile: {active or '(none)'}  [{data.get('path')}]")
        out(f"  Auth: {'ok' if auth_ok else 'MISSING'} - {auth_summary}")
        if not auth_ok:
            out("  Fix: set the key above, then `occ doctor` to verify.")
        if data.get("profiles"):
            out(f"  Saved: {', '.join(sorted(data['profiles']))}  (`occ provider use <name>`)")
        else:
            out("  No saved profiles yet. Run `occ provider wizard`.")
        return 0

    if sub == "list":
        data = _profiles.load_profiles_file()
        profiles = data.get("profiles", {})
        active = config.active_profile or data.get("active")
        if as_json:
            emit({"active": active, "profiles": profiles, "path": data.get("path")})
            return 0
        if not profiles:
            out("  No saved profiles. Run `occ provider wizard`.")
            return 0
        for name in sorted(profiles):
            mark = "*" if name == active else " "
            out(f"  {mark} {_profiles.describe_profile(name, profiles[name])}")
        return 0

    if sub == "show":
        data = _profiles.load_profiles_file()
        if not positionals:
            return run_provider_command(
                config,
                argparse.Namespace(task="", provider_args=[], json=as_json),
                print_fn=out,
            )
        settings = _profiles.get_profile(positionals[0])
        if settings is None:
            out(f"  Unknown profile '{positionals[0]}'. (`occ provider list`)")
            return 1
        if as_json:
            emit({"name": positionals[0].strip(), "settings": settings})
            return 0
        out(f"  {_profiles.describe_profile(positionals[0].strip(), settings)}")
        return 0

    if sub == "save":
        if not positionals:
            out("  Usage: occ provider save <name>")
            return 2
        try:
            saved = _profiles.save_profile(
                positionals[0],
                config.model,
                base_url=config.base_url,
                num_ctx=config.num_ctx,
                max_tokens=config.max_tokens,
                make_active=not no_activate,
            )
        except ValueError as exc:
            out(f"  {exc}")
            return 2
        if not no_activate:
            config.active_profile = saved.name
        data = _profiles.load_profiles_file()
        out(f"  Saved profile '{saved.name}' -> {data.get('path')}")
        out("  Keys are never written there; set them via env vars.")
        return 0

    if sub == "use":
        if not positionals:
            out("  Usage: occ provider use <name>")
            return 2
        try:
            settings = _profiles.set_active_profile(positionals[0])
        except ValueError as exc:
            out(f"  {exc}")
            return 1
        _profiles.apply_profile_to_config(config, settings, replace=True)
        config.active_profile = positionals[0].strip()
        auth_ok, auth_summary, _required = check_provider_auth(config)
        if not auth_ok:
            out(f"  Profile '{config.active_profile}' selected, but auth FAILS: {auth_summary}")
            out("  Set the key above; `occ doctor` verifies. Next `occ` loads this profile.")
            return 1
        out(f"  Active profile: {config.active_profile} ({config.model})")
        out("  Next `occ` loads it. In the REPL, `/provider use` switches immediately.")
        return 0

    if sub == "delete":
        if not positionals:
            out("  Usage: occ provider delete <name>")
            return 2
        if _profiles.delete_profile(positionals[0]):
            if config.active_profile == positionals[0].strip():
                config.active_profile = None
            out(f"  Deleted profile '{positionals[0].strip()}'.")
            return 0
        out(f"  Unknown profile '{positionals[0]}'. (`occ provider list`)")
        return 1

    if sub == "wizard":
        return _run_provider_wizard(config, print_fn=out, input_fn=ask)

    if sub == "models":
        target = positionals[0] if positionals else config.model
        lowered = target.strip().lower()
        if lowered in _profiles.PROVIDER_GUIDE:
            provider = lowered
        else:
            provider = resolve_provider(target, config.base_url)
        models, source = _profiles.fetch_remote_models(
            provider,
            base_url=config.base_url,
            api_key=config.api_key,
            use_cache=not refresh,
        )
        if as_json:
            emit({"provider": provider, "source": source, "models": models[:100]})
            return 0 if models else 1
        if not models:
            out(f"  No catalog ({source}). Pass a full model id explicitly.")
            return 1
        out(f"  {provider} models [{source}, showing {min(50, len(models))} of {len(models)}]:")
        for item in models[:50]:
            out(f"    {item}")
        return 0

    out(f"  Unknown provider subcommand '{sub or '(none)'}'.")
    out("  Usage: occ provider [list|show [name]|save <name>|use <name>|delete <name>|wizard|models [provider]]")
    return 2


def _run_provider_wizard(
    config: AgentConfig,
    *,
    print_fn: object = None,
    input_fn: object = None,
) -> int:
    """Interactive first-run setup. Writes ~/.occ/profiles.yml, never occ.yml."""
    from open_claude_code import profiles as _profiles

    out = print_fn if callable(print_fn) else print
    ask = input_fn if callable(input_fn) else input

    def prompt(label: str, default: str = "") -> str:
        hint = f" [{default}]" if default else ""
        try:
            answer = ask(f"{label}{hint}: ")
        except (EOFError, KeyboardInterrupt):
            return default
        answer = (answer or "").strip()
        return answer or default

    out("")
    out("  Provider setup - saves to ~/.occ/profiles.yml (keys stay in env vars).")
    out("")
    guide = _profiles.PROVIDER_GUIDE
    names = list(guide)
    for index, key in enumerate(names, 1):
        item = guide[key]
        env_label = item["env"] or "(no key)"
        out(f"    {index}. {key:<14} {env_label:<20} e.g. {item['examples']}")
    out("")
    choice = prompt("  Pick a provider [1-7 or name]", "openrouter").strip().lower()
    selected = ""
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        selected = names[int(choice) - 1]
    elif choice in guide:
        selected = choice
    else:
        # Allow pasting a model id directly; infer the provider.
        guessed = resolve_provider(choice, None)
        selected = guessed if guessed in guide else ""
        if not selected:
            out(f"  Unknown provider '{choice}'.")
            return 2
        out(f"  Inferred provider '{selected}' from '{choice}'.")
        default_model = choice
    if not selected:
        out("  Setup cancelled.")
        return 2

    item = guide[selected]
    default_model = locals().get("default_model") or item["examples"].split()[0]
    if selected == "openai-compat":
        default_model = "my-model"
    model = prompt("  Model id", default_model).strip() or default_model
    base_url = ""
    if selected in {"openai-compat", "openai", "openrouter", "ollama"}:
        base_default = config.base_url or ""
        if selected == "openai-compat" and not base_default:
            base_default = "https://api.together.xyz/v1"
        base_url = prompt("  Base URL (blank for default)", base_default).strip()
        if selected == "ollama" and not base_url:
            base_url = ""
    name_default = selected if selected != "openai-compat" else "custom"
    name = prompt("  Save as profile name", name_default).strip() or name_default
    try:
        saved = _profiles.save_profile(
            name,
            model if "/" in model or selected in {"anthropic", "openai", "gemini"} else (
                model if selected == "openai-compat" else f"{selected}/{model.lstrip('/')}"
                if not model.startswith(f"{selected}/") else model
            ),
            base_url=base_url or None,
            num_ctx=config.num_ctx,
            max_tokens=config.max_tokens,
            make_active=True,
        )
    except ValueError as exc:
        out(f"  {exc}")
        return 2
    _profiles.apply_profile_to_config(config, saved.to_dict(), replace=True)
    config.active_profile = saved.name
    auth_ok, auth_summary, required = check_provider_auth(config)
    data = _profiles.load_profiles_file()
    out("")
    out(f"  Saved '{saved.name}': {saved.to_dict()} -> {data.get('path')}")
    if required:
        current = "set" if auth_ok else "MISSING"
        out(f"  Key {required}: {current} - {auth_summary}")
        if not auth_ok:
            out(f"  Next: export {required}='<key>' (never paste keys into chat).")
            out("  Then run `occ doctor` to verify.")
            return 1
    else:
        out("  No API key needed. Make sure `ollama serve` is running.")
        out("  Then run `occ doctor` to verify.")
    out("  `occ --profile "
        + saved.name
        + "` overrides once; plain `occ` loads the active profile.")
    return 0


def switch_provider_in_session(
    config: AgentConfig,
    agent: Agent,
    profile_name: str,
) -> tuple[bool, str]:
    """Switch the live REPL provider to a saved profile. Does not rewrite occ.yml."""
    from open_claude_code import profiles as _profiles

    settings = _profiles.get_profile(profile_name)
    if settings is None:
        known = ", ".join(sorted(_profiles.list_profiles())) or "(no profiles saved)"
        return False, f"unknown profile '{profile_name}'. Known: {known}"
    candidate_model = str(settings.get("model", "") or "").strip()
    candidate_base = settings.get("base_url")
    probe_config = AgentConfig(
        model=candidate_model or config.model,
        base_url=candidate_base,
        api_key=config.api_key,
        num_ctx=settings.get("num_ctx", config.num_ctx),
        max_tokens=int(settings.get("max_tokens", config.max_tokens)),
    )
    auth_ok, auth_summary, _required = check_provider_auth(probe_config)
    if not auth_ok:
        return False, f"auth FAILS for '{profile_name.strip()}': {auth_summary}"
    try:
        new_provider = create_provider(
            model=probe_config.model,
            max_tokens=probe_config.max_tokens,
            api_key=config.api_key,
            base_url=probe_config.base_url,
            prompt_caching=config.prompt_caching,
            num_ctx=probe_config.num_ctx,
        )
    except ProviderError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"cannot create provider: {exc}"
    _profiles.apply_profile_to_config(config, settings, replace=True)
    config.active_profile = profile_name.strip()
    try:
        _profiles.set_active_profile(config.active_profile)
    except ValueError:
        pass
    agent.provider = new_provider
    try:
        agent._context_mgr.provider = new_provider
    except AttributeError:
        pass
    provider_id = resolve_provider(config.model, config.base_url)
    return True, f"switched to '{config.active_profile}' ({config.model} → {provider_id})"



def _json_value(value: object) -> object:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def register_json_listeners(event_bus: EventBus, *, quiet: bool = False) -> None:
    """Write automation-safe lifecycle events as one JSON object per line.

    ``quiet`` keeps only the final assistant message, matching ``--quiet``.
    """
    async def emit(event: object) -> None:
        payload = {"type": type(event).__name__, "data": _json_value(event)}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)

    if not quiet:
        for event_type in (
            Thinking, TokenDelta, ToolCallDelta, UsageUpdated,
            PreToolUse, PostToolUse, ToolDenied, ProviderFailure, Error,
        ):
            event_bus.on(event_type, emit)

    async def emit_final(event: Stop) -> None:
        print(json.dumps({"type": "final", "data": {"text": event.text}}, ensure_ascii=False), flush=True)

    event_bus.on(Stop, emit_final)


def register_exec_listeners(
    event_bus: EventBus,
    args: argparse.Namespace,
    config: AgentConfig,
) -> None:
    """Wire non-interactive exec listeners. Privileged tools are denied by default."""
    if args.json:
        register_json_listeners(event_bus, quiet=args.quiet)
    if args.approval_mode in {"auto", "full-access"}:
        register_approval_listener(event_bus, config=config)
        return

    async def deny_noninteractive(_event: PreToolUse) -> bool:
        return False

    event_bus.on_approval(deny_noninteractive)


def _validate_schema(value: object, schema: dict, label: str = "response") -> None:
    """Deliberately small JSON-schema validator for automation output contracts."""
    expected = schema.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected and not type_matches.get(expected, True):
        raise ValueError(f"{label} must be a JSON {expected}")
    if isinstance(value, dict):
        for required in schema.get("required", []):
            if required not in value:
                raise ValueError(f"{label} is missing required property '{required}'")
        for name, child_schema in schema.get("properties", {}).items():
            if name in value and isinstance(child_schema, dict):
                _validate_schema(value[name], child_schema, f"{label}.{name}")


async def _run_exec(
    args: argparse.Namespace,
    config: AgentConfig,
    agent: Agent,
    middleware_mgr: MiddlewareManager,
    session_store: SessionStore | None,
) -> None:
    """Run one task without an interactive terminal, suitable for scripts and CI."""
    if not args.task:
        raise ValueError("occ exec requires a task argument")
    try:
        result = await agent.run(args.task)
        if args.output_schema:
            schema = json.loads(Path(args.output_schema).read_text(encoding="utf-8"))
            try:
                structured = json.loads(result)
            except json.JSONDecodeError as exc:
                raise ValueError("final response is not valid JSON for --output-schema") from exc
            if not isinstance(schema, dict):
                raise ValueError("--output-schema must contain a JSON object")
            _validate_schema(structured, schema)
        if args.output_last_message:
            Path(args.output_last_message).write_text(result + "\n", encoding="utf-8")
        if not args.json:
            print(result)
    finally:
        try:
            await middleware_mgr.shutdown()
        finally:
            if session_store:
                session_store.close()


def print_splash(config: AgentConfig, middleware_mgr: "MiddlewareManager | None" = None) -> None:
    """Print the Claude Code-inspired welcome banner.

    Layout:
      ┌─────────── Open Claude Code v0.1.0 ───────────┐
      │                                                │
      │        ██████╗   ██████╗  ██████╗              │
      │       ██╔═══██╗ ██╔════╝ ██╔════╝              │
      │       ██║   ██║ ██║      ██║                   │
      │       ╚██████╔╝ ╚██████╗ ╚██████╗              │
      │        ╚═════╝   ╚═════╝  ╚═════╝              │
      │                                                │
      │  Model · Mode · /working/dir                   │
      │                                                │
      │  Active middleware    │  Quick start            │
      │  ✓ MCP (2 servers)   │  /help for commands     │
      │  ✓ Skills (3 loaded) │  /mode to switch        │
      │  ✓ Memory            │  /plan to plan           │
      └────────────────────────────────────────────────┘
    """


    cwd = os.getcwd()
    home = os.path.expanduser("~")
    if cwd.startswith(home):
        cwd = "~" + cwd[len(home):]

    # ── ASCII art "OCC" ──────────────────────────────────────────
    OCC_ART = [
        " ██████╗   ██████╗  ██████╗ ",
        "██╔═══██╗ ██╔════╝ ██╔════╝ ",
        "██║   ██║ ██║      ██║      ",
        "██║   ██║ ██║      ██║      ",
        "╚██████╔╝ ╚██████╗ ╚██████╗ ",
        " ╚═════╝   ╚═════╝  ╚═════╝ ",
    ]

    # Gradient colors for the ASCII art rows (cyan → blue)
    art_colors = [
        "#00e5ff",  # bright cyan
        "#00d4ff",
        "#00bfff",  # deep sky blue
        "#00aaff",
        "#0095ff",
        "#0080ff",  # bright blue
    ]

    # ── Mode badge ───────────────────────────────────────────────
    mode_config = {
        "ask": ("?", "bold yellow"),
        "plan": ("📋", "bold magenta"),
        "agent": ("⚡", "bold green"),
    }
    mode_icon, mode_style = mode_config.get(config.mode, ("❯", "bold cyan"))

    # ── Build the splash content ─────────────────────────────────
    splash = Text()

    # ASCII art block
    for i, line in enumerate(OCC_ART):
        splash.append("    " + line + "\n", style=f"bold {art_colors[i]}")

    splash.append("\n")

    # Model · Mode · Directory info line (centered feel)
    splash.append("    ", style="dim")
    splash.append(config.model, style="bold white")
    splash.append(" · ", style="dim")
    splash.append(f"{mode_icon} {config.mode}", style=mode_style)
    splash.append(" · ", style="dim")
    splash.append("Max ", style="dim")
    splash.append(f"{config.max_tokens // 1000}k", style="bold white")
    splash.append("\n", style="dim")
    splash.append("    ", style="dim")
    splash.append(cwd, style="dim")

    # ── Middleware status (right column) ─────────────────────────
    right = Text()
    right.append("Active middleware\n", style="bold bright_green")

    if middleware_mgr:
        mw_list = middleware_mgr.middlewares if hasattr(middleware_mgr, 'middlewares') else []
        for mw in mw_list:
            name = getattr(mw, 'name', type(mw).__name__.replace('Middleware', ''))
            # Try to get extra info
            detail = ""
            if hasattr(mw, 'manager'):
                mgr = mw.manager
                if hasattr(mgr, 'servers') and mgr.servers:
                    detail = f" ({len(mgr.servers)} server{'s' if len(mgr.servers) != 1 else ''})"
                elif hasattr(mgr, '_loaded_skills'):
                    count = len(mgr._loaded_skills)
                    detail = f" ({count} loaded)" if count else ""
                elif hasattr(mgr, '_files'):
                    count = len(mgr._files)
                    detail = f" ({count} file{'s' if count != 1 else ''})" if count else ""
            right.append("  ✓ ", style="bright_green")
            right.append(f"{name}{detail}\n", style="white")
    else:
        right.append("  ─ none\n", style="dim")

    right.append("\n")
    right.append("Quick start\n", style="bold bright_yellow")
    right.append("  /help  ", style="bold white")
    right.append("for commands\n", style="dim")
    right.append("  /mode  ", style="bold white")
    right.append("switch modes\n", style="dim")
    right.append("  /plan  ", style="bold white")
    right.append("create a plan\n", style="dim")

    # ── Combine in columns ───────────────────────────────────────
    layout = Table.grid(padding=(0, 4))
    layout.add_column(ratio=3)
    layout.add_column(ratio=2)
    layout.add_row(splash, right)

    panel = Panel(
        layout,
        title=f"[bold bright_cyan]⚡ Open Claude Code[/] [dim]v{__version__}[/]",
        subtitle="[dim italic]open-source AI coding agent[/]",
        border_style="bright_cyan",
        padding=(1, 2),
        title_align="center",
        subtitle_align="center",
    )
    console.print()
    console.print(panel)
    console.print()


async def handle_slash_command(
    user_input: str,
    config: AgentConfig,
    agent: Agent,
    middleware_mgr: MiddlewareManager,
    session_store: SessionStore | None = None,
) -> str | None:
    """Handle slash commands. Returns:
      - None if not handled (pass through to mode router)
      - "handled" if fully handled (no further processing)
      - "ask:<text>" / "plan:<text>" / "agent:<text>" for one-shot mode routing
    """
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        console.print()
        help_table = Table(show_header=True, header_style="bold cyan")
        help_table.add_column("Command", style="bold")
        help_table.add_column("Description")
        help_table.add_row("/ask <question>", "Quick answer — no tools, single response")
        help_table.add_row("/plan <task>", "Create plan → review → execute")
        help_table.add_row("/agent <task>", "Full agent mode with tools")
        help_table.add_row("/mode", "Show current mode")
        help_table.add_row("/mode <mode>", "Switch default mode (ask | plan | agent)")
        help_table.add_row("/skill", "Manage skills (list | load <name> | unload <name> | reload)")
        help_table.add_row("/plugin", "Manage plugins (list | reload)")
        help_table.add_row("/mcp", "Manage MCP servers (list | add <name> <cmd> [args] | remove <name>)")
        help_table.add_row("/plan show", "Show current plan/checklist")
        help_table.add_row("/plan progress", "Show plan progress bar")
        help_table.add_row("/plan clear", "Clear the current plan")
        help_table.add_row("/memory", "List loaded memory files (AGENTS.md, CLAUDE.md, etc.)")
        help_table.add_row("/memory reload", "Rescan for memory files")
        help_table.add_row("/memory show", "Preview loaded memory content")
        help_table.add_row("/status", "Show model, permissions, context, and session details")
        help_table.add_row("/cost", "Show token usage, USD cost, API duration, and lines changed")
        help_table.add_row("/provider", "Show model → provider, auth, and saved profiles")
        help_table.add_row("/provider list", "List saved profiles in ~/.occ/profiles.yml")
        help_table.add_row("/provider show <name>", "Show one saved profile")
        help_table.add_row("/provider use <name>", "Switch the live session to a saved profile")
        help_table.add_row("/provider save <name>", "Save current model as a profile (never writes occ.yml)")
        help_table.add_row("/sessions", "List durable local sessions")
        help_table.add_row("/changes", "Show current Git status and uncommitted diff")
        help_table.add_row("/undo <file>", "Restore the latest OCC snapshot for a file")
        help_table.add_row("/rename <title>", "Give the current durable session a title")
        help_table.add_row("/export <path>", "Export current session as a JSON task capsule")
        help_table.add_row("/agent list", "List built-in and .occ/agents subagent roles")
        help_table.add_row("/clear", "Clear conversation history")
        help_table.add_row("/help", "Show this help")
        console.print(help_table)
        console.print()
        return "handled"

    if cmd == "/mode":
        if rest and rest in ("ask", "plan", "agent"):
            old_mode = config.mode
            config.mode = rest
            agent.system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])
            console.print(f"  Mode: {old_mode} → [bold cyan]{config.mode}[/]")
        else:
            mode_style = {"ask": "yellow", "plan": "magenta", "agent": "green"}.get(
                config.mode, "cyan"
            )
            console.print(f"  Current mode: [bold {mode_style}]{config.mode}[/]")
        console.print()
        return "handled"

    if cmd == "/clear":
        agent.history.clear()
        console.print("  Conversation history cleared.", style="dim")
        console.print()
        return "handled"

    if cmd == "/cost":
        console.print()
        tracker = getattr(agent, "cost_tracker", None)
        if tracker is None:
            console.print("  Cost tracking is unavailable.", style="dim")
        else:
            console.print(render_cost_report(tracker.snapshot()))
        console.print()
        return "handled"

    if cmd == "/status":
        context = agent._context_mgr.get_stats(agent.history)
        console.print()
        console.print(f"  Model: [bold cyan]{config.model}[/]")
        console.print(f"  Mode: [bold]{config.mode}[/]  Permission: [bold]{agent.tool_policy.mode}[/]")
        console.print(
            f"  Context: {context.estimated_tokens:,}/{context.max_context_tokens:,} tokens "
            f"({context.utilization:.0%})"
        )
        if session_store:
            console.print(f"  Session: [bold green]{session_store.session_id}[/]")
        else:
            console.print("  Session: [dim]ephemeral (persistence disabled)[/]")
        console.print()
        return "handled"

    if cmd == "/sessions":
        sessions = SessionStore.list_sessions(config)
        console.print()
        if not sessions:
            console.print("  No durable sessions found.", style="dim")
        else:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Session")
            table.add_column("Model")
            table.add_column("Mode")
            table.add_column("Status")
            table.add_column("Updated")
            for item in sessions[:20]:
                table.add_row(
                    str(item.get("session_id", "")),
                    str(item.get("model", "")),
                    str(item.get("mode", "")),
                    str(item.get("status", "")),
                    str(item.get("updated_at", "")),
                )
            console.print(table)
            if len(sessions) > 20:
                console.print(f"  Showing 20 of {len(sessions)} sessions.", style="dim")
        console.print()
        return "handled"

    if cmd == "/changes":
        status = await agent.tools["git_status"]["function"]()
        diff = await agent.tools["git_diff"]["function"]()
        console.print()
        console.print(str(status))
        console.print()
        console.print(str(diff))
        console.print()
        return "handled"

    if cmd == "/undo":
        if not rest:
            console.print("  Usage: /undo <file_path>", style="dim")
        else:
            result = await agent.tools["undo_edit"]["function"](file_path=rest)
            console.print(f"  {result}")
        console.print()
        return "handled"

    if cmd == "/rename":
        if session_store is None:
            console.print("  Session persistence is disabled.", style="dim")
        elif not rest:
            console.print("  Usage: /rename <title>", style="dim")
        else:
            try:
                session_store.rename(rest)
                console.print(f"  Session renamed: [bold]{session_store.metadata['title']}[/]")
            except ValueError as exc:
                console.print(f"  {exc}", style="red")
        console.print()
        return "handled"

    if cmd == "/export":
        if session_store is None:
            console.print("  Session persistence is disabled.", style="dim")
        elif not rest:
            console.print("  Usage: /export <path>", style="dim")
        else:
            try:
                destination = session_store.export(rest)
                console.print(f"  Exported task capsule: [bold green]{destination}[/]")
            except OSError as exc:
                console.print(f"  Export failed: {exc}", style="red")
        console.print()
        return "handled"

    if cmd == "/agent":
        if rest not in {"", "list"}:
            return f"agent:{rest}"
        registry = AgentRegistry(search_dirs=config.agents_dirs)
        personas = PersonaRegistry(search_dirs=config.personas_dirs)
        definitions = registry.definitions
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name")
        table.add_column("Source")
        table.add_column("Permission")
        table.add_column("Max turns")
        table.add_column("Description")
        for definition in definitions.values():
            table.add_row(
                definition.name,
                "built-in" if definition.builtin else "project",
                definition.permission_mode,
                str(definition.max_turns),
                definition.description,
            )
        console.print(table)
        if personas.personas:
            persona_table = Table(show_header=True, header_style="bold cyan", title="Personas")
            persona_table.add_column("Name")
            persona_table.add_column("Description")
            for persona in personas.personas.values():
                persona_table.add_row(persona.name, persona.description)
            console.print(persona_table)
        console.print()
        return "handled"

    if cmd == "/provider":
        import shlex

        from open_claude_code import profiles as _profiles

        try:
            tokens = shlex.split(rest) if rest else []
        except ValueError:
            tokens = rest.split() if rest else []
        sub = tokens[0].lower() if tokens else ""
        args_rest = tokens[1:] if tokens else []

        if sub in {"", "show", "status"} and not args_rest:
            data = _profiles.load_profiles_file()
            provider_id = resolve_provider(config.model, config.base_url)
            auth_ok, auth_summary, _required = check_provider_auth(config)
            console.print()
            console.print(f"  Model: [bold cyan]{config.model}[/] → {provider_id}")
            if config.base_url:
                console.print(f"  Base URL: {config.base_url}")
            active = config.active_profile or data.get("active")
            console.print(f"  Profile: {active or '(none)'}  [{data.get('path')}]")
            console.print(f"  Auth: {'ok' if auth_ok else 'MISSING'} — {auth_summary}")
            if data.get("profiles"):
                console.print(f"  Saved: {', '.join(sorted(data['profiles']))}")
            else:
                console.print("  No saved profiles yet. `/provider save <name>` remembers this one.")
            console.print("  `occ provider wizard` walks first-run setup. `occ doctor` verifies.", style="dim")
            console.print()
            return "handled"

        if sub == "show" and args_rest:
            settings = _profiles.get_profile(args_rest[0])
            console.print()
            if settings is None:
                console.print(f"  Unknown profile '{args_rest[0]}'. (`/provider list`)", style="red")
            else:
                console.print(f"  {_profiles.describe_profile(args_rest[0].strip(), settings)}")
            console.print()
            return "handled"

        if sub == "list":
            data = _profiles.load_profiles_file()
            profiles = data.get("profiles", {})
            active = config.active_profile or data.get("active")
            console.print()
            if not profiles:
                console.print("  No saved profiles. `/provider save <name>` remembers this one.", style="dim")
            else:
                table = Table(show_header=True, header_style="bold cyan")
                table.add_column("Active")
                table.add_column("Name", style="bold")
                table.add_column("Model")
                table.add_column("Base URL")
                for name in sorted(profiles):
                    settings = profiles[name]
                    table.add_row(
                        "*" if name == active else "",
                        name,
                        str(settings.get("model", "")),
                        str(settings.get("base_url", "")),
                    )
                console.print(table)
            console.print()
            return "handled"

        if sub == "save":
            if not args_rest:
                console.print("  Usage: /provider save <name>", style="dim")
                console.print()
                return "handled"
            try:
                saved = _profiles.save_profile(
                    args_rest[0],
                    config.model,
                    base_url=config.base_url,
                    num_ctx=config.num_ctx,
                    max_tokens=config.max_tokens,
                    make_active=True,
                )
            except ValueError as exc:
                console.print(f"  {exc}", style="red")
                console.print()
                return "handled"
            config.active_profile = saved.name
            console.print(f"  Saved profile '{saved.name}' (occ.yml untouched; keys never written).")
            console.print()
            return "handled"

        if sub == "use":
            if not args_rest:
                console.print("  Usage: /provider use <name>", style="dim")
                console.print()
                return "handled"
            ok, message = switch_provider_in_session(config, agent, args_rest[0])
            style = "green" if ok else "red"
            console.print(f"  {message}", style=style)
            console.print()
            return "handled"

        if sub == "delete":
            if not args_rest:
                console.print("  Usage: /provider delete <name>", style="dim")
                console.print()
                return "handled"
            if _profiles.delete_profile(args_rest[0]):
                if config.active_profile == args_rest[0].strip():
                    config.active_profile = None
                console.print(f"  Deleted profile '{args_rest[0].strip()}'.")
            else:
                console.print(f"  Unknown profile '{args_rest[0]}'.", style="red")
            console.print()
            return "handled"

        if sub == "models":
            refresh = "--refresh" in args_rest or "--no-cache" in args_rest
            positionals = [item for item in args_rest if not item.startswith("--")]
            target = positionals[0] if positionals else config.model
            lowered = target.strip().lower()
            if lowered in _profiles.PROVIDER_GUIDE:
                provider_id = lowered
            else:
                provider_id = resolve_provider(target, config.base_url)
            models, source = _profiles.fetch_remote_models(
                provider_id,
                base_url=config.base_url,
                api_key=config.api_key,
                use_cache=not refresh,
            )
            console.print()
            if not models:
                console.print(f"  No catalog ({source}). Pass a full model id explicitly.", style="dim")
            else:
                console.print(f"  {provider_id} models [{source}, showing {min(30, len(models))} of {len(models)}]:")
                for item in models[:30]:
                    console.print(f"    {item}")
            console.print()
            return "handled"

        if sub == "wizard":
            console.print()
            console.print("  Interactive setup runs in the shell: `occ provider wizard`", style="dim")
            console.print("  It saves to ~/.occ/profiles.yml (keys stay in env vars).")
            console.print("  Quick version: `/provider save <name>` remembers this model,")
            console.print("  `/provider use <name>` switches without touching occ.yml.")
            console.print()
            return "handled"

        console.print("  Usage: /provider [list|show [name]|save <name>|use <name>|delete <name>|models|wizard]", style="dim")
        console.print()
        return "handled"

    # Try middleware slash commands
    mw_result = await middleware_mgr.handle_slash_command(cmd, rest)
    if mw_result is not None:
        # Handle async MCP operations
        if mw_result.startswith("mcp_async:"):
            mcp_mw = middleware_mgr.get("mcp")
            if mcp_mw and hasattr(mcp_mw, "handle_async_command"):
                await mcp_mw.handle_async_command(mw_result[10:])
                # Refresh tools after MCP changes
                agent.tools.update(middleware_mgr.collect_tools())
            return "handled"
        return mw_result

    # One-shot mode commands: /ask <text>, /plan <text>, /agent <text>
    if cmd in ("/ask", "/plan", "/agent") and rest:
        mode = cmd[1:]  # strip leading /
        return f"{mode}:{rest}"

    return None


async def run() -> None:
    """Main async entry point."""
    args = parse_args()
    config = resolve_config(args)

    if args.command == "doctor":
        raise SystemExit(
            run_doctor_cli(config, json_output=args.json, report_path=args.report)
        )

    if args.command == "provider":
        raise SystemExit(run_provider_command(config, args))

    session_store: SessionStore | None = None
    if args.resume:
        session_store = SessionStore.resume(args.resume, config=config)
        # A resumed task should keep its original model/mode unless the caller
        # deliberately supplied an override for this invocation.
        previous = session_store.metadata
        if args.model is None and isinstance(previous.get("model"), str):
            config.model = previous["model"]
        if args.mode is None and previous.get("mode") in {"ask", "plan", "agent"}:
            config.mode = previous["mode"]
    elif config.persist_sessions:
        session_store = SessionStore.create(
            config=config,
            model=config.model,
            mode=config.mode,
        )

    # Create provider
    provider = create_provider(
        model=config.model,
        max_tokens=config.max_tokens,
        api_key=config.api_key,
        base_url=config.base_url,
        prompt_caching=config.prompt_caching,
        num_ctx=config.num_ctx,
    )

    # Set up event bus and listeners. Exec is non-interactive: privileged
    # tools are denied unless --approval-mode auto/full-access is explicit.
    event_bus = EventBus()
    if args.command == "exec":
        register_exec_listeners(event_bus, args, config)
    else:
        register_ui_listeners(event_bus)
        register_approval_listener(event_bus, config=config)
        register_logging_listeners(event_bus)

    # Get system prompt for current mode
    system_prompt = MODE_PROMPTS.get(config.mode, MODE_PROMPTS["agent"])

    # Build middleware stack
    # Order matters: memory first, then planning, skills, hooks, plugins, MCP
    memory_mw = MemoryMiddleware(
        search_dirs=config.memory_dirs if config.memory_dirs else None
    )
    planning_mw = PlanningMiddleware()
    skills_mw = SkillsMiddleware(
        search_dirs=config.skills_dirs if config.skills_dirs else None
    )
    hooks_mw = HooksMiddleware(config=config)
    plugin_mw = PluginMiddleware(config=config)
    mcp_mw = MCPMiddleware(config=config)

    middleware_mgr = MiddlewareManager([memory_mw, planning_mw, skills_mw, hooks_mw, plugin_mw, mcp_mw])

    # Get base tools (without skills — handled by middleware now)
    tools = get_tools(
        skill_manager=skills_mw.manager,
        config=config,
        event_bus=event_bus,
        session_id=session_store.session_id if session_store else None,
    )

    # Create agent with middleware
    agent = Agent(
        provider=provider,
        event_bus=event_bus,
        tools=tools,
        system_prompt=system_prompt,
        config=config,
        middleware_manager=middleware_mgr,
        session_store=session_store,
    )

    if session_store and args.resume:
        agent.history = session_store.load_history()
        agent.cost_tracker.restore_from_session(session_store)

    # Initialize middleware (connects MCP servers, etc.)
    await agent.initialize()

    # Legacy compat — attach managers for any code that still accesses them
    agent._skill_manager = skills_mw.manager
    agent._plugin_manager = plugin_mw.manager
    agent._mcp_manager = mcp_mw.manager

    if args.command == "exec":
        await _run_exec(args, config, agent, middleware_mgr, session_store)
        return

    print_splash(config, middleware_mgr)
    if session_store:
        action = "Resumed" if args.resume else "Session"
        console.print(f"  {action}: [dim]{session_store.session_id}[/]")
        console.print()

    session = PromptSession()

    try:
        # REPL loop
        while True:
            # Show mode indicator + plan progress in prompt
            mode_char = {"ask": "?", "plan": "📋", "agent": "❯"}.get(config.mode, "❯")
            pt_style = {"ask": "ansiyellow", "plan": "ansimagenta", "agent": "ansicyan"}.get(
                config.mode, "ansicyan"
            )

            # Add plan progress to prompt if active
            plan_hint = ""
            if planning_mw.store.is_active:
                done, total = planning_mw.store.progress
                plan_hint = f" <ansigreen>[{done}/{total}]</ansigreen>"

            try:
                # use prompt_async to play nicely with our async loop
                user_input = await session.prompt_async(
                    HTML(f"<{pt_style}><b>{mode_char}</b></{pt_style}>{plan_hint} ")
                )
            except (KeyboardInterrupt, EOFError):
                console.print("\nGoodbye! 👋", style="dim")
                return

            stripped = user_input.strip()
            if not stripped:
                continue

            # Handle slash commands
            if stripped.startswith("/"):
                result = await handle_slash_command(
                    stripped, config, agent, middleware_mgr, session_store
                )
                if result == "handled":
                    continue
                if result and ":" in result:
                    # One-shot mode: "ask:question" / "plan:task" / "agent:task"
                    mode, text = result.split(":", 1)
                    await run_mode(mode, agent, text)
                    console.print()
                    continue

            # Normal input — route through current default mode
            await run_mode(config.mode, agent, stripped)
            console.print()
    finally:
        try:
            await middleware_mgr.shutdown()
        finally:
            if session_store:
                session_store.close()


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\nGoodbye! 👋", style="dim")


if __name__ == "__main__":
    main()
