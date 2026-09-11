"""Sub-agent runtime: types, background wait, resume, steer, workflow, isolation."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus, SubagentStart, SubagentStop
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.planning import PlanningMiddleware
from open_claude_code.providers.base import Provider, ProviderResponse, TextBlock, ToolUseBlock
from open_claude_code.subagents.registry import AgentRegistry, PersonaRegistry, builtin_definitions
from open_claude_code.tools.policy import ToolPolicy


class MockProvider(Provider):
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self.messages: list[list[dict]] = []
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def send(self, messages, tools, system_prompt) -> ProviderResponse:
        async with self._lock:
            self.messages.append(messages)
            return self._responses.pop(0)


def _tools(**fns) -> dict:
    tools = {}
    for name, fn in fns.items():
        tools[name] = {
            "function": fn,
            "schema": {"name": name, "input_schema": {"type": "object"}},
        }
    tools["spawn_agent"] = {
        "function": None,
        "schema": {"name": "spawn_agent", "input_schema": {"type": "object"}},
    }
    return tools


def test_builtin_roles_are_always_registered():
    registry = AgentRegistry(search_dirs=["/no/such/agents"])
    names = set(registry.definitions)
    assert {"explore", "plan", "general-purpose"} <= names
    assert registry.get("explore").permission_mode == "read-only"
    assert registry.get("general-purpose").permission_mode == "inherit"
    assert "read_file" in registry.get("explore").tools
    assert "write_plan" in registry.get("plan").tools
    assert registry.get("general-purpose").tools == ()


def test_project_role_shadows_builtin(tmp_path: Path):
    root = tmp_path / "agents"
    root.mkdir()
    root.joinpath("explore.md").write_text(
        "---\nname: explore\ndescription: Custom explorer\npermission_mode: read-only\n---\nCustom body.",
        encoding="utf-8",
    )
    registry = AgentRegistry([root])
    assert registry.get("explore").description == "Custom explorer"
    assert registry.get("explore").builtin is False
    assert builtin_definitions()["explore"].builtin is True


def test_persona_registry_reads_markdown(tmp_path: Path):
    root = tmp_path / "personas"
    root.mkdir()
    root.joinpath("terse.md").write_text(
        "---\nname: terse\ndescription: Short answers\n---\nBe brief.",
        encoding="utf-8",
    )
    registry = PersonaRegistry([root])
    persona = registry.get("terse")
    assert persona is not None
    assert "Be brief." in persona.instructions


@pytest.mark.asyncio
async def test_unknown_role_is_reported():
    provider = MockProvider([ProviderResponse(thinking=None, content=[TextBlock(text="unused")])])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    results = await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "x", "agent_type": "nope"})
    ])
    assert "Unknown subagent role" in results[0]["content"]


def _wait_content(history: list[dict], tool_use_id: str) -> str:
    for message in history:
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("tool_use_id") == tool_use_id:
                return str(item.get("content", ""))
    return ""


@pytest.mark.asyncio
async def test_same_turn_background_spawn_then_wait():
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="spawn-1",
                name="spawn_agent",
                input={"task": "look", "agent_type": "explore", "background": True},
            ),
            ToolUseBlock(id="wait-1", name="wait_agent", input={}),
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="child-result")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="parent-done")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    result = await parent.run("delegate")
    assert result == "parent-done"
    assert "child-result" in _wait_content(parent.history, "wait-1")


@pytest.mark.asyncio
async def test_prompt_alias_and_extra_wait_kwargs():
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="from-prompt")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    started = await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"prompt": "look via prompt", "agent_type": "explore", "background": True},
        )
    ])
    assert "status: running" in started[0]["content"]
    report = await parent.subagents.wait_tool(thought="ignore me", timeout_ms="0")
    assert "status: running" in report
    report = await parent.subagents.wait_tool()
    assert "from-prompt" in report


@pytest.mark.asyncio
async def test_background_spawn_then_wait():
    child_provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="child done")]),
    ])
    parent = Agent(
        provider=child_provider,
        event_bus=EventBus(),
        tools=_tools(),
        config=AgentConfig(),
    )
    results = await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "look around", "agent_type": "explore", "background": True},
        )
    ])
    assert "status: running" in results[0]["content"]
    assert "sa-" in results[0]["content"]
    report = await parent.subagents.wait_tool()
    assert "child done" in report
    assert "status: completed" in report


@pytest.mark.asyncio
async def test_wait_snapshot_does_not_block():
    gate = asyncio.Event()

    class SlowProvider(MockProvider):
        async def send(self, messages, tools, system_prompt) -> ProviderResponse:
            await gate.wait()
            return await super().send(messages, tools, system_prompt)

    provider = SlowProvider([ProviderResponse(thinking=None, content=[TextBlock(text="later")])])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "slow", "background": True, "agent_type": "explore"},
        )
    ])
    snapshot = await parent.subagents.wait_tool(timeout_ms=0)
    assert "status: running" in snapshot
    gate.set()
    done = await parent.subagents.wait_tool()
    assert "later" in done


@pytest.mark.asyncio
async def test_kill_cancels_running_child():
    gate = asyncio.Event()

    class SlowProvider(MockProvider):
        async def send(self, messages, tools, system_prompt) -> ProviderResponse:
            await gate.wait()
            return ProviderResponse(thinking=None, content=[TextBlock(text="should not")])

    parent = Agent(provider=SlowProvider([]), event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "hang", "background": True, "agent_type": "explore"},
        )
    ])
    job_id = next(iter(parent.subagents.jobs))
    report = await parent.subagents.kill_tool(agent_id=job_id)
    assert "cancelled" in report
    gate.set()


@pytest.mark.asyncio
async def test_steer_injects_parent_message():
    first_send = asyncio.Event()
    release = asyncio.Event()

    class GateProvider(Provider):
        def __init__(self) -> None:
            self.stage = 0
            self.seen: list[list[dict]] = []

        @property
        def model_name(self) -> str:
            return "mock-model"

        async def send(self, messages, tools, system_prompt) -> ProviderResponse:
            self.seen.append(messages)
            if self.stage == 0:
                self.stage = 1
                first_send.set()
                await release.wait()
                return ProviderResponse(
                    thinking=None,
                    content=[ToolUseBlock(id="n1", name="noop", input={})],
                )
            return ProviderResponse(thinking=None, content=[TextBlock(text="steered")])

    async def noop() -> str:
        return "ok"

    provider = GateProvider()
    parent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=_tools(noop=noop),
        config=AgentConfig(),
    )
    await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "work", "background": True, "agent_type": "explore"},
        )
    ])
    job_id = next(iter(parent.subagents.jobs))
    await first_send.wait()
    steered = await parent.subagents.send_tool(agent_id=job_id, message="focus on auth")
    assert "Steered" in steered
    release.set()
    report = await parent.subagents.wait_tool(agent_ids=[job_id])
    assert "steered" in report
    blob = str(provider.seen)
    assert "focus on auth" in blob


@pytest.mark.asyncio
async def test_resume_from_completed_child():
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="research notes")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="plan from notes")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    first = await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "research", "agent_type": "explore"})
    ])
    source_id = first[0]["content"].split()[1]
    second = await parent.subagents.run([
        ToolUseBlock(
            id="s2",
            name="spawn_agent",
            input={"task": "now plan it", "agent_type": "explore", "resume_from": source_id},
        )
    ])
    assert "plan from notes" in second[0]["content"]
    child = list(parent.subagents.jobs.values())[-1].agent
    roles = [item.get("role") for item in child.history]
    assert roles.count("user") >= 2


@pytest.mark.asyncio
async def test_resume_rejects_type_mismatch():
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="done")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    first = await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "research", "agent_type": "explore"})
    ])
    source_id = first[0]["content"].split()[1]
    second = await parent.subagents.run([
        ToolUseBlock(
            id="s2",
            name="spawn_agent",
            input={"task": "write it", "agent_type": "general-purpose", "resume_from": source_id},
        )
    ])
    assert "same agent_type" in second[0]["content"]


@pytest.mark.asyncio
async def test_nested_spawn_is_denied():
    provider = MockProvider([
        ProviderResponse(
            thinking=None,
            content=[ToolUseBlock(id="inner", name="spawn_agent", input={"task": "nope"})],
        ),
        ProviderResponse(thinking=None, content=[TextBlock(text="parent done")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "delegate", "agent_type": "explore"})
    ])
    child = next(iter(parent.subagents.jobs.values())).agent
    assert "Nested spawn_agent is not allowed" in str(child.history)


@pytest.mark.asyncio
async def test_child_planning_store_is_isolated():
    parent_plan = PlanningMiddleware()
    provider = MockProvider([
        ProviderResponse(
            thinking=None,
            content=[
                ToolUseBlock(
                    id="p1",
                    name="write_plan",
                    input={"title": "child", "steps": ["step"]},
                )
            ],
        ),
        ProviderResponse(thinking=None, content=[TextBlock(text="planned")]),
    ])
    parent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=_tools(),
        config=AgentConfig(),
        middleware_manager=MiddlewareManager([parent_plan]),
    )
    await parent.initialize()
    await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "plan it", "agent_type": "plan"})
    ])
    assert parent_plan.store.is_active is False


@pytest.mark.asyncio
async def test_persona_appended_to_child_prompt(tmp_path: Path):
    personas = tmp_path / "personas"
    personas.mkdir()
    personas.joinpath("terse.md").write_text("---\nname: terse\n---\nNO FLUFF.", encoding="utf-8")
    captured = {}

    class CaptureProvider(MockProvider):
        async def send(self, messages, tools, system_prompt) -> ProviderResponse:
            captured["prompt"] = system_prompt
            return await super().send(messages, tools, system_prompt)

    parent = Agent(
        provider=CaptureProvider([ProviderResponse(thinking=None, content=[TextBlock(text="ok")])]),
        event_bus=EventBus(),
        tools=_tools(),
        config=AgentConfig(personas_dirs=[str(personas)]),
    )
    await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "x", "agent_type": "explore", "persona": "terse"},
        )
    ])
    assert "NO FLUFF." in captured["prompt"]


@pytest.mark.asyncio
async def test_workflow_runs_phases_in_order():
    provider = MockProvider([
        ProviderResponse(thinking=None, content=[TextBlock(text="job-a")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="job-b")]),
    ])
    parent = Agent(provider=provider, event_bus=EventBus(), tools=_tools(), config=AgentConfig())
    report = await parent.subagents.workflow_tool(
        phases=[
            {
                "name": "scan",
                "jobs": [
                    {"task": "a", "agent_type": "explore"},
                    {"task": "b", "agent_type": "explore"},
                ],
            }
        ]
    )
    assert "# scan" in report
    assert "job-a" in report
    assert "job-b" in report


@pytest.mark.asyncio
async def test_workflow_caps_phase_size():
    parent = Agent(
        provider=MockProvider([]),
        event_bus=EventBus(),
        tools=_tools(),
        config=AgentConfig(),
    )
    jobs = [{"task": f"t{i}", "agent_type": "explore"} for i in range(9)]
    report = await parent.subagents.workflow_tool(phases=[{"name": "too-big", "jobs": jobs}])
    assert "max is 8" in report


@pytest.mark.asyncio
async def test_events_include_agent_id():
    events: list[object] = []

    async def collect(event):
        events.append(event)

    bus = EventBus()
    bus.on(SubagentStart, collect)
    bus.on(SubagentStop, collect)
    provider = MockProvider([ProviderResponse(thinking=None, content=[TextBlock(text="ok")])])
    parent = Agent(provider=provider, event_bus=bus, tools=_tools(), config=AgentConfig())
    await parent.subagents.run([
        ToolUseBlock(id="s1", name="spawn_agent", input={"task": "x", "agent_type": "explore"})
    ])
    starts = [e for e in events if isinstance(e, SubagentStart)]
    stops = [e for e in events if isinstance(e, SubagentStop)]
    assert starts and starts[0].agent_id.startswith("sa-")
    assert starts[0].agent_type == "explore"
    assert stops and stops[0].status == "completed"


def test_general_purpose_child_can_write_when_parent_can():
    writes = []

    async def write_file(file_path: str, content: str) -> str:
        writes.append((file_path, content))
        return "written"

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="spawn-1", name="spawn_agent", input={"task": "edit it"})
        ]),
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(id="write-1", name="write_file", input={"file_path": "ok.txt", "content": "yes"})
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Child complete")]),
        ProviderResponse(thinking=None, content=[TextBlock(text="Parent complete")]),
    ])
    agent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=_tools(write_file=write_file),
        config=AgentConfig(),
        tool_policy=ToolPolicy(mode="workspace-write"),
    )
    assert asyncio.run(agent.run("delegate this")) == "Parent complete"
    assert writes == [("ok.txt", "yes")]


@pytest.mark.asyncio
async def test_worktree_isolation_and_apply(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("base\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    try:
        git("init")
        git("config", "user.email", "occ@test")
        git("config", "user.name", "OCC")
        git("add", ".")
        git("commit", "-m", "init")
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git not available: {exc}")

    async def write_file(file_path: str, content: str) -> str:
        Path(file_path).write_text(content, encoding="utf-8")
        return "written"

    provider = MockProvider([
        ProviderResponse(thinking=None, content=[
            ToolUseBlock(
                id="w1",
                name="write_file",
                input={"file_path": "hello.txt", "content": "child\n"},
            )
        ]),
        ProviderResponse(thinking=None, content=[TextBlock(text="edited")]),
    ])
    parent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=_tools(write_file=write_file),
        config=AgentConfig(workspace_roots=[str(repo)], writable_roots=[str(repo)]),
    )
    results = await parent.subagents.run([
        ToolUseBlock(
            id="s1",
            name="spawn_agent",
            input={"task": "edit privately", "isolation": "worktree", "agent_type": "general-purpose"},
        )
    ])
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "base\n"
    job = next(iter(parent.subagents.jobs.values()))
    assert job.worktree_path
    assert Path(job.worktree_path).joinpath("hello.txt").read_text(encoding="utf-8") == "child\n"
    applied = await parent.subagents.apply_tool(agent_id=job.id)
    assert "hello.txt" in applied
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "child\n"
    assert "worktree:" in results[0]["content"]
