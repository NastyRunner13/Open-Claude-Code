"""CLI slash-command routing and `occ exec` safety."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus, PreToolUse, Stop, Thinking
from open_claude_code.main import (
    handle_slash_command,
    parse_args,
    register_exec_listeners,
    register_json_listeners,
    resolve_config,
)
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.planning import PlanningMiddleware


def _slash_env(tmp_path=None):
    config = AgentConfig()
    if tmp_path is not None:
        config.agents_dirs = [str(tmp_path / "agents")]
    agent = MagicMock()
    agent.history = []
    mgr = MiddlewareManager([PlanningMiddleware()])
    return config, agent, mgr


@pytest.mark.asyncio
async def test_plan_task_routes_to_oneshot_plan_mode():
    config, agent, mgr = _slash_env()
    result = await handle_slash_command("/plan refactor auth", config, agent, mgr)
    assert result == "plan:refactor auth"


@pytest.mark.asyncio
async def test_plan_show_stays_checklist_command():
    config, agent, mgr = _slash_env()
    result = await handle_slash_command("/plan show", config, agent, mgr)
    assert result == "handled"


@pytest.mark.asyncio
async def test_plan_bare_stays_checklist_command():
    config, agent, mgr = _slash_env()
    result = await handle_slash_command("/plan", config, agent, mgr)
    assert result == "handled"


@pytest.mark.asyncio
async def test_agent_task_routes_to_oneshot_agent_mode():
    config, agent, mgr = _slash_env()
    result = await handle_slash_command("/agent refactor auth", config, agent, mgr)
    assert result == "agent:refactor auth"


@pytest.mark.asyncio
async def test_agent_list_is_handled(tmp_path):
    config, agent, mgr = _slash_env(tmp_path)
    result = await handle_slash_command("/agent list", config, agent, mgr)
    assert result == "handled"


@pytest.mark.asyncio
async def test_ask_task_still_oneshot():
    config, agent, mgr = _slash_env()
    result = await handle_slash_command("/ask what is a monad", config, agent, mgr)
    assert result == "ask:what is a monad"


def test_exec_missing_task_exits_2(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["occ", "exec"])
    with pytest.raises(SystemExit) as exc:
        parse_args()
    assert exc.value.code == 2


def test_exec_parses_json_and_quiet(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["occ", "exec", "do the thing", "--json", "--quiet", "--approval-mode", "suggest"],
    )
    args = parse_args()
    assert args.command == "exec"
    assert args.task == "do the thing"
    assert args.json is True
    assert args.quiet is True
    assert args.approval_mode == "suggest"


def test_exec_default_does_not_skip_approval(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["occ", "exec", "summarize the repo"])
    args = parse_args()
    config = resolve_config(args)
    assert config.skip_approval is False


def test_exec_auto_sets_skip_approval(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["occ", "exec", "implement it", "--approval-mode", "auto"]
    )
    args = parse_args()
    config = resolve_config(args)
    assert config.skip_approval is True
    assert config.permission_mode == "workspace-write"


@pytest.mark.asyncio
async def test_exec_default_denies_privileged_tools(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["occ", "exec", "write a file"])
    args = parse_args()
    config = resolve_config(args)
    bus = EventBus()
    register_exec_listeners(bus, args, config)
    approved = await bus.emit_approval(
        PreToolUse(tool_name="write_file", tool_params={"file_path": "x"}, requires_approval=True)
    )
    assert approved is False


@pytest.mark.asyncio
async def test_exec_suggest_denies_privileged_tools(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["occ", "exec", "write a file", "--approval-mode", "suggest"]
    )
    args = parse_args()
    config = resolve_config(args)
    bus = EventBus()
    register_exec_listeners(bus, args, config)
    approved = await bus.emit_approval(
        PreToolUse(tool_name="run_shell", tool_params={"command": "mkdir x"}, requires_approval=True)
    )
    assert approved is False


@pytest.mark.asyncio
async def test_exec_auto_approves_policy_permitted_tools(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["occ", "exec", "write a file", "--approval-mode", "auto"]
    )
    args = parse_args()
    config = resolve_config(args)
    bus = EventBus()
    register_exec_listeners(bus, args, config)
    approved = await bus.emit_approval(
        PreToolUse(tool_name="write_file", tool_params={"file_path": "x"}, requires_approval=True)
    )
    assert approved is True


@pytest.mark.asyncio
async def test_exec_json_emits_final_event(capsys):
    bus = EventBus()
    register_json_listeners(bus)
    await bus.emit(Stop(text="all done"))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload == {"type": "final", "data": {"text": "all done"}}


@pytest.mark.asyncio
async def test_exec_quiet_json_omits_progress(capsys):
    bus = EventBus()
    register_json_listeners(bus, quiet=True)
    await bus.emit(Thinking(text="hmm"))
    await bus.emit(Stop(text="done"))
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["type"] == "final"


@pytest.mark.asyncio
async def test_exec_ephemeral_disables_persistence(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["occ", "exec", "task", "--ephemeral"])
    args = parse_args()
    config = resolve_config(args)
    assert config.persist_sessions is False
    assert config.persist_snapshots is False
