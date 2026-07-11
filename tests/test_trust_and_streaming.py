"""Regression coverage for reversible edits, web safety, and provider streams."""

from __future__ import annotations

import asyncio
from pathlib import Path

from open_claude_code.agent import Agent
from open_claude_code.events import EventBus, UsageUpdated
from open_claude_code.providers.base import (
    Provider,
    ProviderResponse,
    ProviderUsage,
    TextBlock,
    TransientProviderError,
)
from open_claude_code.tools.apply_patch import apply_patch
from open_claude_code.tools.context import ToolContext
from open_claude_code.tools.edit_file import edit_file
from open_claude_code.tools.multi_edit import multi_edit
from open_claude_code.tools.read_url import read_url
from open_claude_code.tools.undo_edit import undo_edit
from open_claude_code.tools.write_file import write_file
from open_claude_code.sessions import SessionStore
from open_claude_code.config import AgentConfig
from open_claude_code.skills.loader import SkillManager
from open_claude_code.subagents.registry import AgentRegistry


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        cwd=tmp_path,
        max_output=10_000,
        workspace_roots=[tmp_path],
        writable_roots=[tmp_path],
        snapshots_dir=tmp_path / ".occ" / "snapshots",
        session_id="test-session",
    )


def test_write_snapshot_and_undo_restore_original(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("before\n", encoding="utf-8")
    context = _context(tmp_path)

    written = asyncio.run(write_file("sample.txt", "after\n", _context=context))
    assert written.success
    assert written.metadata["snapshot_id"]
    assert "-before" in written.metadata["diff"]

    undone = asyncio.run(undo_edit(file_path="sample.txt", _context=context))
    assert undone.success
    assert path.read_text(encoding="utf-8") == "before\n"


def test_multi_edit_is_atomic_when_one_replacement_fails(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("one\ntwo\n", encoding="utf-8")
    result = asyncio.run(
        multi_edit(
            "sample.txt",
            [{"old_string": "one", "new_string": "ONE"}, {"old_string": "missing", "new_string": "x"}],
            _context=_context(tmp_path),
        )
    )
    assert not result.success
    assert path.read_text(encoding="utf-8") == "one\ntwo\n"


def test_apply_patch_validates_then_creates_reversible_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("one\n", encoding="utf-8")
    context = _context(tmp_path)
    result = asyncio.run(
        apply_patch(
            "--- a/sample.txt\n+++ b/sample.txt\n@@ -1 +1 @@\n-one\n+two\n",
            _context=context,
        )
    )
    assert result.success
    assert path.read_text(encoding="utf-8") == "two\n"
    snapshot_id = result.metadata["snapshot_ids"][0]
    assert asyncio.run(undo_edit(snapshot_id=snapshot_id, _context=context)).success
    assert path.read_text(encoding="utf-8") == "one\n"


def test_read_url_rejects_non_http_scheme_before_network_access(tmp_path: Path) -> None:
    result = asyncio.run(read_url("file:///etc/passwd", _context=_context(tmp_path)))
    assert not result.success
    assert "http and https" in (result.error or "")


class _RetryProvider(Provider):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "retry-model"

    async def send(self, messages: list[dict], tools: list[dict], system_prompt: str) -> ProviderResponse:
        self.calls += 1
        if self.calls == 1:
            raise TransientProviderError("rate limited", status_code=429)
        return ProviderResponse(
            thinking=None,
            content=[TextBlock("ok")],
            usage=ProviderUsage(input_tokens=3, output_tokens=2),
        )


def test_agent_retries_transient_provider_error_and_emits_usage() -> None:
    provider = _RetryProvider()
    events: list[UsageUpdated] = []
    bus = EventBus()

    async def collect(event: UsageUpdated) -> None:
        events.append(event)

    bus.on(UsageUpdated, collect)
    agent = Agent(provider=provider, event_bus=bus, tools={})
    assert asyncio.run(agent.run("test")) == "ok"
    assert provider.calls == 2
    assert events and events[0].input_tokens == 3


def test_session_can_be_renamed_and_exported(tmp_path: Path) -> None:
    config = AgentConfig(sessions_dir=str(tmp_path / "sessions"))
    store = SessionStore.create(config=config, model="mock", mode="agent", cwd=tmp_path)
    store.record_history({"role": "user", "content": "hello"})
    store.rename("Useful task")
    destination = store.export(tmp_path / "capsule.json")
    assert store.metadata["title"] == "Useful task"
    assert destination.is_file()
    assert "history_append" in destination.read_text(encoding="utf-8")


def test_skill_catalog_is_lightweight_and_respects_model_invocation_flag(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    public = root / "public"
    private = root / "private"
    public.mkdir(parents=True)
    private.mkdir()
    public.joinpath("SKILL.md").write_text(
        "---\nname: Public\ndescription: Public workflow\n---\nVery detailed instructions", encoding="utf-8"
    )
    private.joinpath("SKILL.md").write_text(
        "---\nname: Private\ndescription: Interactive only\ndisable_model_invocation: true\n---\nSecret workflow", encoding="utf-8"
    )
    manager = SkillManager(search_dirs=[str(root)])
    assert manager.available["Public"].instructions == ""
    assert "Public" in manager.get_catalog_prompt()
    assert "Private" not in manager.get_catalog_prompt()
    assert "Very detailed instructions" in manager.load("Public").instructions  # type: ignore[union-attr]


def test_custom_agent_registry_reads_role_metadata(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    root.joinpath("reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Read-only reviewer\ntools: [read_file, git_diff]\nmax_turns: 12\n---\nReview carefully.",
        encoding="utf-8",
    )
    definition = AgentRegistry([root]).get("reviewer")
    assert definition is not None
    assert definition.permission_mode == "read-only"
    assert definition.tools == ("read_file", "git_diff")
    assert definition.max_turns == 12
