"""Sub-agent manager — lifecycle, concurrency, isolation, and parent-only tools.

The agent loop delegates spawn_agent calls here. wait/kill/steer/apply/workflow
are bound as regular tools on the parent Agent.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from open_claude_code.events import EventBus, SubagentStart, SubagentStop
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.planning import PlanningMiddleware
from open_claude_code.providers.base import ToolUseBlock
from open_claude_code.subagents.registry import AgentRegistry, PersonaRegistry
from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.policy import ToolPolicy, clamp_permission_mode
from open_claude_code.tools.spawn_agent import PARENT_ONLY_TOOLS, PLAN_TOOL_NAMES

if TYPE_CHECKING:
    from open_claude_code.agent import Agent

MAX_RESULT_CHARS = 12000
MAX_PHASE_JOBS = 8
MAX_WORKFLOW_JOBS = 32
WAIT_TIMEOUT_CAP_MS = 3_600_000


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _truncate(text: str) -> str:
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return text[:MAX_RESULT_CHARS] + "\n[Sub-agent output truncated]"


async def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except (OSError, asyncio.TimeoutError) as exc:
        return 1, str(exc)
    output = (stdout + stderr).decode("utf-8", errors="replace").strip()
    return process.returncode or 0, output


@dataclass
class SubagentJob:
    """One child run owned by a parent agent."""

    id: str
    task: str
    description: str
    agent_type: str
    status: str = "running"
    result: str = ""
    worktree_path: str = ""
    isolation: str = "none"
    background: bool = False
    allowed_tools: tuple[str, ...] = ()
    agent: Any = None
    asyncio_task: asyncio.Task | None = None
    inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    followups: asyncio.Queue = field(default_factory=asyncio.Queue)


class SubagentManager:
    """Creates and tracks child agents for one parent.

    Design:
      - Jobs live on the parent so wait/kill/steer/resume work across turns.
      - Children get an isolated EventBus and their own PlanningMiddleware.
      - Nested spawn is stripped; parent-only tools never reach a child.
      - Multiple spawns in one turn start concurrently via asyncio.Task.
    """

    def __init__(self, parent_agent: "Agent") -> None:
        self.parent = parent_agent
        search_dirs = parent_agent.config.agents_dirs if parent_agent.config else None
        persona_dirs = parent_agent.config.personas_dirs if parent_agent.config else None
        self.registry = AgentRegistry(search_dirs=search_dirs)
        self.personas = PersonaRegistry(search_dirs=persona_dirs)
        self.jobs: dict[str, SubagentJob] = {}
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"sa-{self._seq:04d}-{uuid.uuid4().hex[:6]}"

    def format_job(self, job: SubagentJob) -> str:
        lines = [
            f"Subagent {job.id} ({job.agent_type})",
            f"status: {job.status}",
        ]
        if job.description:
            lines.append(f"description: {job.description}")
        lines.append(f"task: {job.task[:200]}")
        if job.worktree_path:
            lines.append(f"worktree: {job.worktree_path}")
        if job.status == "running":
            lines.append("Use wait_agent to collect the result.")
        elif job.result:
            lines.append(_truncate(job.result))
        return "\n".join(lines)

    async def run(self, spawn_blocks: list[ToolUseBlock]) -> list[dict]:
        """Start every approved spawn. Block only on children that did not set background."""
        started: list[tuple[ToolUseBlock, SubagentJob | dict]] = []
        for block in spawn_blocks:
            started.append((block, await self._start(block)))

        blocking = [
            item.asyncio_task
            for _, item in started
            if isinstance(item, SubagentJob) and not item.background and item.asyncio_task
        ]
        if blocking:
            await asyncio.gather(*blocking, return_exceptions=True)

        results = []
        for block, item in started:
            if isinstance(item, dict):
                content = item.get("content", "Sub-agent error")
            else:
                content = self.format_job(item)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
        return results

    async def _start(self, block: ToolUseBlock) -> SubagentJob | dict:
        payload = block.input if isinstance(block.input, dict) else {}
        task = str(payload.get("task") or payload.get("prompt") or "").strip()
        if not task:
            return {"content": "spawn_agent requires a task."}

        resume_from = str(payload.get("resume_from") or "").strip()
        source = self.jobs.get(resume_from) if resume_from else None
        if resume_from and source is None:
            return {"content": f"Unknown subagent '{resume_from}' for resume_from."}
        if source is not None and source.status == "running":
            return {"content": f"Cannot resume running subagent '{resume_from}'."}

        requested_name = str(payload.get("agent_type") or payload.get("agent_name") or "").strip()
        if source is not None and not requested_name:
            requested_name = source.agent_type
        if not requested_name:
            requested_name = "general-purpose"
        if source is not None and requested_name != source.agent_type:
            return {
                "content": (
                    f"resume_from requires the same agent_type "
                    f"('{source.agent_type}'), not '{requested_name}'."
                )
            }

        definition = self.registry.get(requested_name)
        if definition is None:
            available = ", ".join(self.registry.definitions) or "none"
            return {"content": f"Unknown subagent role '{requested_name}'. Available roles: {available}"}

        persona_name = str(payload.get("persona") or "").strip()
        persona = self.personas.get(persona_name) if persona_name else None
        if persona_name and persona is None:
            available = ", ".join(self.personas.personas) or "none"
            return {"content": f"Unknown persona '{persona_name}'. Available personas: {available}"}

        isolation = str(payload.get("isolation") or "none").strip().lower() or "none"
        cwd_value = str(payload.get("cwd") or "").strip()
        if source is not None:
            isolation = source.isolation
            cwd_value = source.worktree_path if source.isolation == "worktree" else cwd_value
        if isolation not in {"none", "worktree"}:
            return {"content": f"Unknown isolation '{isolation}'. Use none or worktree."}
        if isolation == "worktree" and cwd_value and source is None:
            return {"content": "cwd and isolation=worktree are mutually exclusive."}

        job_id = self._next_id()
        worktree_path = ""
        child_cwd: Path | None = Path(cwd_value).expanduser() if cwd_value and isolation != "worktree" else None
        if isolation == "worktree":
            if source is not None and source.worktree_path:
                worktree_path = source.worktree_path
                child_cwd = Path(worktree_path)
            else:
                created, error = await self._create_worktree(job_id)
                if created is None:
                    return {"content": error}
                worktree_path = str(created)
                child_cwd = created

        job = SubagentJob(
            id=job_id,
            task=task,
            description=str(payload.get("description") or "").strip(),
            agent_type=definition.name,
            isolation=isolation,
            background=_as_bool(payload.get("background"), False),
            worktree_path=worktree_path,
            allowed_tools=definition.tools,
        )
        try:
            job.agent = self._build_child(
                job=job,
                definition=definition,
                payload=payload,
                persona_instructions=persona.instructions if persona else "",
                child_cwd=child_cwd,
                source=source,
            )
        except Exception as exc:
            return {"content": f"Sub-agent error: {exc}"}

        await self.parent.event_bus.emit(
            SubagentStart(
                task=task,
                agent_id=job.id,
                agent_type=job.agent_type,
                background=job.background,
                isolation=isolation,
            )
        )
        job.asyncio_task = asyncio.create_task(self._execute(job), name=f"occ-subagent-{job.id}")
        self.jobs[job.id] = job
        return job

    def _build_child(
        self,
        *,
        job: SubagentJob,
        definition: Any,
        payload: dict,
        persona_instructions: str,
        child_cwd: Path | None,
        source: SubagentJob | None,
    ) -> "Agent":
        from open_claude_code.agent import Agent
        from open_claude_code.config import AgentConfig
        from open_claude_code.providers import create_provider
        from open_claude_code.sessions import SessionStore
        from open_claude_code.tools import get_tools

        role_mode = definition.permission_mode
        parent_mode = self.parent.tool_policy.mode
        requested_mode = str(payload.get("permission_mode") or "")
        policy_mode = clamp_permission_mode(requested_mode, parent_mode, role_mode)
        policy_base = ToolPolicy.from_config(self.parent.config)
        disallowed = tuple(
            dict.fromkeys((*policy_base.disallowed_tools, *definition.disallowed_tools))
        )
        policy = ToolPolicy(mode=policy_mode, disallowed_tools=disallowed)

        max_turns = definition.max_turns
        try:
            if payload.get("max_turns") is not None:
                max_turns = max(1, min(int(payload["max_turns"]), 1000))
        except (TypeError, ValueError):
            pass

        sub_config = replace(self.parent.config) if self.parent.config else AgentConfig()
        sub_config.permission_mode = policy_mode
        sub_config.shell_policy = policy_mode
        if job.isolation == "worktree" and job.worktree_path:
            sub_config.workspace_roots = [job.worktree_path]
            sub_config.writable_roots = [job.worktree_path]

        model = definition.model or self.parent.provider.model_name
        sub_provider = self.parent.provider
        if definition.model and definition.model != self.parent.provider.model_name:
            sub_config.model = definition.model
            sub_provider = create_provider(
                model=sub_config.model,
                max_tokens=sub_config.max_tokens,
                api_key=sub_config.api_key,
                base_url=sub_config.base_url,
                prompt_caching=sub_config.prompt_caching,
            )
        else:
            sub_config.model = model

        sub_session = None
        if self.parent.session_store and sub_config.persist_sessions:
            sub_session = SessionStore.create(
                config=sub_config,
                model=model,
                mode="agent",
                parent_session_id=self.parent.session_store.session_id,
            )

        sub_bus = EventBus()
        if child_cwd is not None or job.isolation == "worktree":
            rebound = get_tools(
                skill_manager=getattr(self.parent, "_skill_manager", None),
                config=sub_config,
                event_bus=sub_bus,
                session_id=sub_session.session_id if sub_session else None,
                cwd=child_cwd,
            )
            sub_tools = dict(rebound)
            for name, tool in self.parent.tools.items():
                if name in sub_tools or name in PARENT_ONLY_TOOLS or name in PLAN_TOOL_NAMES:
                    continue
                sub_tools[name] = tool
        else:
            sub_tools = {
                name: tool
                for name, tool in self.parent.tools.items()
                if name not in PARENT_ONLY_TOOLS
            }
        if definition.tools:
            allowed = set(definition.tools)
            sub_tools = {name: tool for name, tool in sub_tools.items() if name in allowed}
        for name in PARENT_ONLY_TOOLS:
            sub_tools.pop(name, None)

        prompt = self.parent._build_system_prompt()
        prompt = f"{prompt}\n\n# Subagent Role: {definition.name}\n{definition.system_prompt}"
        if persona_instructions:
            prompt = f"{prompt}\n\n# Persona: overlay\n{persona_instructions}"

        wants_plan = (not definition.tools) or bool(set(definition.tools) & PLAN_TOOL_NAMES)
        child = Agent(
            provider=sub_provider,
            event_bus=sub_bus,
            tools=sub_tools,
            system_prompt=prompt,
            config=sub_config,
            tool_policy=policy,
            middleware_manager=MiddlewareManager([PlanningMiddleware()] if wants_plan else []),
            session_store=sub_session,
            max_turns=max_turns,
            is_subagent=True,
            inbox=job.inbox,
        )
        if source is not None and source.agent is not None:
            child.history = list(source.agent.history)
        return child

    async def _execute(self, job: SubagentJob) -> None:
        try:
            await job.agent.initialize()
            for name in PARENT_ONLY_TOOLS:
                job.agent.tools.pop(name, None)
            if job.allowed_tools:
                allowed = set(job.allowed_tools)
                job.agent.tools = {
                    name: tool for name, tool in job.agent.tools.items() if name in allowed
                }
            result = await job.agent.run(job.task)
            while True:
                queued: list[str] = []
                while True:
                    try:
                        queued.append(job.followups.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if not queued:
                    break
                for message in queued:
                    result = await job.agent.run(message)
            job.result = result
            job.status = "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.result = "Sub-agent cancelled"
            raise
        except Exception as exc:
            job.status = "failed"
            job.result = f"Sub-agent error: {exc}"
        finally:
            if job.agent and job.agent.session_store:
                job.agent.session_store.close()
            await self.parent.event_bus.emit(
                SubagentStop(
                    task=job.task,
                    result=job.result,
                    agent_id=job.id,
                    agent_type=job.agent_type,
                    status=job.status,
                    worktree_path=job.worktree_path,
                )
            )

    async def _create_worktree(self, job_id: str) -> tuple[Path | None, str]:
        parent_cwd = Path.cwd()
        if self.parent.config and self.parent.config.workspace_roots:
            parent_cwd = Path(self.parent.config.workspace_roots[0]).expanduser()
            if not parent_cwd.is_absolute():
                parent_cwd = (Path.cwd() / parent_cwd).resolve()
        code, root = await _git(["rev-parse", "--show-toplevel"], parent_cwd)
        if code != 0:
            return None, f"isolation=worktree requires a git repository: {root}"
        git_root = Path(root)
        dest = git_root / ".occ" / "worktrees" / job_id
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        code, output = await _git(["worktree", "add", "--detach", str(dest), "HEAD"], git_root)
        if code != 0:
            return None, f"git worktree add failed: {output}"
        return dest, ""

    def _resolve_jobs(self, agent_ids: list[str] | str | None, agent_id: str = "") -> list[SubagentJob] | str:
        ids: list[str] = []
        if isinstance(agent_ids, str) and agent_ids.strip():
            ids.append(agent_ids.strip())
        elif isinstance(agent_ids, list):
            ids.extend(str(item).strip() for item in agent_ids if str(item).strip())
        if agent_id.strip():
            ids.append(agent_id.strip())
        ids = list(dict.fromkeys(ids))
        if not ids:
            return [job for job in self.jobs.values() if job.status == "running"] or list(self.jobs.values())
        resolved = []
        missing = []
        for item in ids:
            job = self.jobs.get(item)
            if job is None:
                missing.append(item)
            else:
                resolved.append(job)
        if missing:
            return f"Unknown subagent id(s): {', '.join(missing)}"
        return resolved

    async def wait_tool(
        self,
        agent_ids: list[str] | str | None = None,
        timeout_ms: int | None = None,
        agent_id: str = "",
        **_kwargs: Any,
    ) -> str:
        resolved = self._resolve_jobs(agent_ids, str(agent_id or ""))
        if isinstance(resolved, str):
            return resolved
        if not resolved:
            return "No sub-agents to wait on."
        pending = [job.asyncio_task for job in resolved if job.asyncio_task and not job.asyncio_task.done()]
        parsed_timeout: int | None
        try:
            parsed_timeout = None if timeout_ms in (None, "") else int(timeout_ms)
        except (TypeError, ValueError):
            parsed_timeout = None
        if pending and parsed_timeout != 0:
            timeout: float | None = None
            if parsed_timeout is not None:
                timeout = max(0, min(parsed_timeout, WAIT_TIMEOUT_CAP_MS)) / 1000
            await asyncio.wait(pending, timeout=timeout)
        return "\n\n".join(self.format_job(job) for job in resolved)

    async def kill_tool(self, agent_id: str = "", **_kwargs: Any) -> str:
        job = self.jobs.get(agent_id)
        if job is None:
            return f"Unknown subagent '{agent_id}'."
        if job.status != "running" or job.asyncio_task is None:
            return self.format_job(job)
        job.asyncio_task.cancel()
        try:
            await job.asyncio_task
        except (asyncio.CancelledError, Exception):
            pass
        if job.status == "running":
            job.status = "cancelled"
            job.result = "Sub-agent cancelled"
        return self.format_job(job)

    async def send_tool(self, agent_id: str = "", message: str = "", queue: bool = False, **_kwargs: Any) -> str:
        job = self.jobs.get(agent_id)
        if job is None:
            return f"Unknown subagent '{agent_id}'."
        if job.status != "running":
            return f"Subagent '{agent_id}' is {job.status}; use resume_from to continue a finished child."
        text = str(message).strip()
        if not text:
            return "send_agent_message requires a message."
        if _as_bool(queue, False):
            await job.followups.put(text)
            return f"Queued follow-up for {job.id}."
        await job.inbox.put(text)
        return f"Steered {job.id}."

    async def apply_tool(self, agent_id: str = "", **_kwargs: Any) -> str:
        job = self.jobs.get(agent_id)
        if job is None:
            return f"Unknown subagent '{agent_id}'."
        if not job.worktree_path:
            return f"Subagent '{agent_id}' has no worktree."
        worktree = Path(job.worktree_path)
        if not worktree.is_dir():
            return f"Worktree missing: {worktree}"
        changed = await self._worktree_changed_files(worktree)
        if not changed:
            return "No worktree changes to apply."
        context = ToolContext.from_config(
            self.parent.config,
            event_bus=self.parent.event_bus,
            session_id=self.parent.session_store.session_id if self.parent.session_store else None,
        )
        applied: list[str] = []
        for rel in changed:
            src = worktree / rel
            if not src.is_file():
                continue
            decision = context.check_write_path(rel)
            if not decision.allowed:
                return f"apply denied for {rel}: {decision.reason}"
            decision.resolved_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, decision.resolved_path)
            applied.append(rel)
        return "Applied:\n" + "\n".join(applied) if applied else "No file changes to copy."

    async def _worktree_changed_files(self, worktree: Path) -> list[str]:
        files: list[str] = []
        for args in (
            ["diff", "--name-only", "HEAD"],
            ["ls-files", "--others", "--exclude-standard"],
        ):
            code, output = await _git(args, worktree)
            if code != 0 or not output:
                continue
            files.extend(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())
        return list(dict.fromkeys(files))

    async def workflow_tool(self, phases: list[dict] | None = None, **_kwargs: Any) -> str:
        if not phases or not isinstance(phases, list):
            return "run_workflow requires a phases array."
        total = 0
        reports: list[str] = []
        for index, phase in enumerate(phases, start=1):
            if not isinstance(phase, dict):
                return f"Phase {index} is not an object."
            jobs = phase.get("jobs") or []
            if not isinstance(jobs, list) or not jobs:
                return f"Phase {index} has no jobs."
            if len(jobs) > MAX_PHASE_JOBS:
                return f"Phase {index} has {len(jobs)} jobs; max is {MAX_PHASE_JOBS}."
            if total + len(jobs) > MAX_WORKFLOW_JOBS:
                return f"Workflow would exceed {MAX_WORKFLOW_JOBS} jobs."
            total += len(jobs)
            title = str(phase.get("name") or f"phase-{index}")
            blocks = []
            for job_index, spec in enumerate(jobs, start=1):
                if not isinstance(spec, dict) or not spec.get("task"):
                    return f"Phase {index} job {job_index} requires a task."
                payload = {
                    "task": spec.get("task"),
                    "description": spec.get("description") or title,
                    "agent_type": spec.get("agent_type") or spec.get("agent_name") or "general-purpose",
                    "permission_mode": spec.get("permission_mode") or "",
                    "isolation": spec.get("isolation") or "none",
                    "persona": spec.get("persona") or "",
                    "background": True,
                }
                blocks.append(ToolUseBlock(id=f"wf-{index}-{job_index}", name="spawn_agent", input=payload))
            spawn_results = await self.run(blocks)
            ids = []
            failures = []
            for result in spawn_results:
                first = str(result["content"]).splitlines()[0] if result["content"] else ""
                parts = first.split()
                if len(parts) >= 2 and parts[0] == "Subagent":
                    ids.append(parts[1])
                else:
                    failures.append(str(result["content"]))
            wait_report = await self.wait_tool(agent_ids=ids) if ids else "No children started."
            body = wait_report
            if failures:
                body = "\n".join(failures) + ("\n" + body if ids else "")
            reports.append(f"# {title}\n{body}")
        return "\n\n".join(reports)
