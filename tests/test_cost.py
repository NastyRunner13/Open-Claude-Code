"""Cost tracker, price table, /cost rendering, and max_budget_usd."""

from __future__ import annotations

import asyncio
import json

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.cost import (
    CostTracker,
    billable_tokens,
    count_diff_lines,
    format_usd,
    lookup_price,
    render_cost_report,
)
from open_claude_code.events import EventBus, Stop, UsageUpdated
from open_claude_code.providers.base import ToolUseBlock
from open_claude_code.sessions import SessionStore

from tests.fakes import ScriptedProvider, ScriptedTurn


def test_lookup_known_and_unknown_models():
    assert lookup_price("claude-sonnet-4-20250514").known
    assert lookup_price("openrouter/anthropic/claude-sonnet-4").known
    assert lookup_price("gpt-4o-mini").input == 0.15
    assert lookup_price("gpt-4o").input == 2.50
    assert lookup_price("mystery-hosted-model").known is False
    assert lookup_price("ollama/llama3.2").known
    assert lookup_price("ollama/llama3.2").input == 0.0


def test_custom_prices_override_table():
    price = lookup_price(
        "mystery-hosted-model",
        {"mystery-hosted-model": {"input": 1.0, "output": 5.0}},
    )
    assert price.known
    assert price.input == 1.0
    assert price.output == 5.0


def test_unknown_price_never_prints_zero_dollars():
    tracker = CostTracker()
    tracker.record_usage(UsageUpdated(input_tokens=12, output_tokens=4, model="totally-unknown"))
    text = render_cost_report(tracker.snapshot())
    assert "price unknown" in text
    assert "$0.00" not in text


def test_ollama_is_free_not_unknown():
    tracker = CostTracker()
    tracker.record_usage(UsageUpdated(input_tokens=12, output_tokens=4, model="ollama/qwen2.5"))
    snap = tracker.snapshot()
    assert snap.price_unknown is False
    assert snap.known_usd == 0.0
    assert "$0.00" in render_cost_report(snap)
    assert "price unknown" not in render_cost_report(snap)


def test_format_usd_distinguishes_unknown_from_zero():
    assert format_usd(0.0, known=True) == "$0.00"
    assert format_usd(0.0, known=False) == "price unknown"
    assert format_usd(None, known=False) == "price unknown"
    assert format_usd(0.0004, known=True) == "$0.0004"


def test_openai_cache_is_subset_of_input():
    assert billable_tokens(100, 40, 0) == (60, 40, 0)


def test_anthropic_cache_is_disjoint():
    assert billable_tokens(100, 50, 20) == (100, 50, 20)
    assert billable_tokens(100, 50, 0, "claude-sonnet-4") == (100, 50, 0)
    assert billable_tokens(100, 50, 0, "openrouter/anthropic/claude-sonnet-4") == (100, 50, 0)


def test_diff_line_counts_ignore_headers():
    diff = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n"
        " keep\n"
        "-old\n"
        "+new\n"
        "+also\n"
    )
    assert count_diff_lines(diff) == (2, 1)


def test_tracker_records_file_tool_diffs():
    tracker = CostTracker()
    tracker.record_tool_result(
        "write_file",
        "wrote it\n\nDiff:\n--- a/x\n+++ b/x\n+hello\n-old\n",
    )
    tracker.record_tool_result("read_file", "+not a diff header really\n")
    snap = tracker.snapshot()
    assert snap.lines_added == 1
    assert snap.lines_removed == 1


def test_sonnet_cost_math():
    tracker = CostTracker()
    tracker.record_usage(
        UsageUpdated(
            input_tokens=1_000_000,
            output_tokens=0,
            model="claude-sonnet-4-20250514",
        )
    )
    assert abs(tracker.snapshot().known_usd - 3.0) < 1e-9


def test_mixed_known_and_unknown_total_label():
    tracker = CostTracker()
    tracker.record_usage(
        UsageUpdated(input_tokens=1_000_000, output_tokens=0, model="claude-sonnet-4")
    )
    tracker.record_usage(
        UsageUpdated(input_tokens=10, output_tokens=2, model="mystery-model")
    )
    snap = tracker.snapshot()
    assert "price unknown" in snap.total_label()
    assert "$3.00" in snap.total_label() or "$3" in snap.total_label()


def test_budget_stops_after_first_priced_turn():
    from open_claude_code.providers.base import ProviderUsage

    config = AgentConfig(
        max_budget_usd=0.0001,
        model_prices={"scripted-model": {"input": 1000.0, "output": 1000.0}},
        provider_retry_base_delay=0.0,
        context_compaction=False,
    )
    calls: list[str] = []

    async def echo(message: str) -> str:
        calls.append(message)
        return f"echoed:{message}"

    tools = {
        "echo": {
            "function": echo,
            "schema": {
                "name": "echo",
                "description": "Echo",
                "input_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            },
        }
    }
    provider = ScriptedProvider(
        [
            ScriptedTurn(
                tool_calls=(ToolUseBlock(id="t1", name="echo", input={"message": "ping"}),),
                usage=ProviderUsage(input_tokens=100, output_tokens=100),
            ),
            ScriptedTurn.reply("should-not-run"),
        ]
    )
    stops: list[Stop] = []
    bus = EventBus()

    async def collect(event: Stop) -> None:
        stops.append(event)

    bus.on(Stop, collect)
    agent = Agent(provider=provider, event_bus=bus, tools=tools, config=config)
    result = asyncio.run(agent.run("go"))
    assert "Stopped:" in result
    assert "max_budget_usd" in result
    assert calls == ["ping"]
    assert provider.remaining == 1
    assert stops and "Stopped:" in stops[0].text


def test_budget_zero_skips_provider():
    config = AgentConfig(
        max_budget_usd=0.0,
        model_prices={"scripted-model": {"input": 1.0, "output": 1.0}},
        provider_retry_base_delay=0.0,
        context_compaction=False,
    )
    provider = ScriptedProvider([ScriptedTurn.reply("nope")])
    agent = Agent(provider=provider, event_bus=EventBus(), tools={}, config=config)
    result = asyncio.run(agent.run("go"))
    assert "Stopped:" in result
    assert provider.remaining == 1


def test_unknown_model_does_not_trip_budget():
    config = AgentConfig(max_budget_usd=0.01, provider_retry_base_delay=0.0, context_compaction=False)
    provider = ScriptedProvider([ScriptedTurn.reply("ok", input_tokens=10_000, output_tokens=10_000)])
    agent = Agent(provider=provider, event_bus=EventBus(), tools={}, config=config)
    result = asyncio.run(agent.run("go"))
    assert result == "ok"


def test_restore_usage_from_session(tmp_path):
    config = AgentConfig(sessions_dir=str(tmp_path / "sessions"))
    store = SessionStore.create(config=config, model="claude-sonnet-4", mode="agent", cwd=tmp_path)
    store.record(
        "usage_updated",
        UsageUpdated(input_tokens=20, output_tokens=5, latency_ms=12.0, model="claude-sonnet-4").__dict__,
    )
    store.record_tool_result("edit_file", "tool-1", "--- a/a\n+++ b/a\n+x\n-y\n")

    restored = CostTracker.from_config(config)
    restored.restore_from_session(store)
    snap = restored.snapshot()
    assert snap.total_input_tokens == 20
    assert snap.total_output_tokens == 5
    assert snap.lines_added == 1
    assert snap.lines_removed == 1
    assert snap.api_ms == 12.0


def test_agent_records_usage_and_diff_lines():
    config = AgentConfig(
        provider_retry_base_delay=0.0,
        context_compaction=False,
        model_prices={"scripted-model": {"input": 1.0, "output": 2.0}},
    )

    async def write_file(file_path: str, content: str) -> str:
        return "ok\n\nDiff:\n--- a/x\n+++ b/x\n+hello\n"

    tools = {
        "write_file": {
            "function": write_file,
            "schema": {
                "name": "write_file",
                "description": "Write",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
            },
        }
    }
    provider = ScriptedProvider(
        [
            ScriptedTurn.tools(
                ToolUseBlock(id="t1", name="write_file", input={"file_path": "x", "content": "hello"}),
                text="",
            ),
            ScriptedTurn.reply("done", input_tokens=8, output_tokens=2),
        ]
    )
    agent = Agent(
        provider=provider,
        event_bus=EventBus(),
        tools=tools,
        config=config,
    )
    assert asyncio.run(agent.run("write")) == "done"
    snap = agent.cost_tracker.snapshot()
    assert snap.lines_added == 1
    assert snap.requests >= 1
    payload = snap.to_dict()
    assert "scripted-model" in payload["models"]
    assert json.dumps(payload)


def test_empty_session_render():
    assert "No usage recorded" in render_cost_report(CostTracker().snapshot())
