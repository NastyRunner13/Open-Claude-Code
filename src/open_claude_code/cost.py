"""Token-cost accounting for `/cost` and optional `max_budget_usd`.

Prices are USD per million tokens. Unknown models report "price unknown"
instead of $0.00. Ollama is treated as free. Custom YAML `model_prices`
override the built-in table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from open_claude_code.events.types import UsageUpdated

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig
    from open_claude_code.sessions.store import SessionStore


_DIFF_TOOLS = frozenset({"write_file", "edit_file", "multi_edit", "apply_patch"})
_STRIP_PREFIXES = ("openrouter/", "groq/", "ollama/")


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens. `known=False` means do not print a dollar amount."""

    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_creation: float = 0.0
    known: bool = True


# Longest-prefix match. List prices lag vendors; YAML overrides win.
# SYNC: cost-price-table
_PRICE_TABLE: tuple[tuple[str, ModelPrice], ...] = (
    ("claude-opus-4", ModelPrice(15.0, 75.0, 1.50, 18.75)),
    ("claude-sonnet-4", ModelPrice(3.0, 15.0, 0.30, 3.75)),
    ("claude-haiku-4", ModelPrice(0.80, 4.0, 0.08, 1.0)),
    ("claude-3-7-sonnet", ModelPrice(3.0, 15.0, 0.30, 3.75)),
    ("claude-3.7-sonnet", ModelPrice(3.0, 15.0, 0.30, 3.75)),
    ("claude-3-5-sonnet", ModelPrice(3.0, 15.0, 0.30, 3.75)),
    ("claude-3-5-haiku", ModelPrice(0.80, 4.0, 0.08, 1.0)),
    ("claude-3-opus", ModelPrice(15.0, 75.0, 1.50, 18.75)),
    ("claude-3-haiku", ModelPrice(0.25, 1.25, 0.03, 0.31)),
    ("gpt-4o-mini", ModelPrice(0.15, 0.60, 0.075, 0.0)),
    ("gpt-4o", ModelPrice(2.50, 10.0, 1.25, 0.0)),
    ("gpt-4.1-mini", ModelPrice(0.40, 1.60, 0.10, 0.0)),
    ("gpt-4.1", ModelPrice(2.00, 8.00, 0.50, 0.0)),
    ("chatgpt-4o", ModelPrice(5.00, 15.0, 2.50, 0.0)),
    ("o4-mini", ModelPrice(1.10, 4.40, 0.275, 0.0)),
    ("o3-mini", ModelPrice(1.10, 4.40, 0.275, 0.0)),
    ("o3", ModelPrice(10.0, 40.0, 2.50, 0.0)),
    ("o1-mini", ModelPrice(1.10, 4.40, 0.275, 0.0)),
    ("o1", ModelPrice(15.0, 60.0, 7.50, 0.0)),
    ("gemini-2.5-pro", ModelPrice(1.25, 10.0, 0.125, 0.0)),
    ("gemini-2.0-flash", ModelPrice(0.10, 0.40, 0.025, 0.0)),
    ("gemini-1.5-pro", ModelPrice(1.25, 5.00, 0.3125, 0.0)),
    ("gemini-1.5-flash", ModelPrice(0.075, 0.30, 0.01875, 0.0)),
    ("llama-3.3-70b-versatile", ModelPrice(0.59, 0.79)),
    ("llama-3.1-8b-instant", ModelPrice(0.05, 0.08)),
    ("openai/gpt-oss-120b", ModelPrice(0.15, 0.60)),
    ("openai/gpt-oss-20b", ModelPrice(0.075, 0.30)),
)

_UNKNOWN = ModelPrice(known=False)
_FREE = ModelPrice(0.0, 0.0, 0.0, 0.0, known=True)


def _normalize_model(model: str) -> str:
    name = model.strip().lower()
    for prefix in _STRIP_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _price_from_mapping(raw: Mapping[str, Any]) -> ModelPrice | None:
    if not raw:
        return None
    try:
        input_rate = float(raw.get("input", 0.0) or 0.0)
        output_rate = float(raw.get("output", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None
    cache_read_raw = raw.get("cache_read")
    cache_creation_raw = raw.get("cache_creation")
    try:
        cache_read = (
            float(cache_read_raw) if cache_read_raw is not None else input_rate * 0.1
        )
        cache_creation = (
            float(cache_creation_raw) if cache_creation_raw is not None else input_rate * 1.25
        )
    except (TypeError, ValueError):
        return None
    return ModelPrice(input_rate, output_rate, cache_read, cache_creation, known=True)


def lookup_price(
    model: str,
    custom: Mapping[str, Mapping[str, Any] | ModelPrice] | None = None,
) -> ModelPrice:
    """Return the price row for a model id. Unknown hosted models are not free."""
    if not model.strip():
        return _UNKNOWN
    lowered = model.strip().lower()
    if custom:
        for key, value in custom.items():
            if key.lower() == lowered:
                if isinstance(value, ModelPrice):
                    return value
                parsed = _price_from_mapping(value)
                if parsed is not None:
                    return parsed
    if lowered.startswith("ollama/") or lowered.startswith("ollama:"):
        return _FREE
    stripped = _normalize_model(model)
    if custom:
        for key, value in custom.items():
            if key.lower() in {stripped, _normalize_model(key)}:
                if isinstance(value, ModelPrice):
                    return value
                parsed = _price_from_mapping(value)
                if parsed is not None:
                    return parsed
    candidates: list[tuple[int, ModelPrice]] = []
    for key, price in _PRICE_TABLE:
        if stripped == key or stripped.startswith(key) or stripped.endswith("/" + key):
            candidates.append((len(key), price))
        elif key in stripped.split("/"):
            candidates.append((len(key), price))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    if lowered.startswith("ollama/"):
        return _FREE
    return _UNKNOWN


def billable_tokens(
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    model: str = "",
) -> tuple[int, int, int]:
    """Split usage into disjoint input / cache-read / cache-write buckets.

    Anthropic reports three disjoint counters (cache hits have cache_read
    without cache_creation). OpenAI reports cached_tokens as a subset of
    prompt_tokens.
    """
    input_tokens = max(0, int(input_tokens or 0))
    cache_read_tokens = max(0, int(cache_read_tokens or 0))
    cache_creation_tokens = max(0, int(cache_creation_tokens or 0))
    lowered = model.lower()
    if (
        cache_creation_tokens > 0
        or "claude" in lowered
        or "anthropic" in lowered
    ):
        return input_tokens, cache_read_tokens, cache_creation_tokens
    uncached = max(0, input_tokens - cache_read_tokens)
    return uncached, cache_read_tokens, 0


def cost_usd(tokens: tuple[int, int, int], output_tokens: int, price: ModelPrice) -> float | None:
    if not price.known:
        return None
    inp, cache_read, cache_write = tokens
    return (
        inp * price.input
        + max(0, output_tokens) * price.output
        + cache_read * price.cache_read
        + cache_write * price.cache_creation
    ) / 1_000_000


def count_diff_lines(text: str) -> tuple[int, int]:
    """Count added/removed lines in a unified diff, ignoring file headers."""
    added = 0
    removed = 0
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def format_usd(amount: float | None, *, known: bool) -> str:
    """Print a dollar amount, or 'price unknown' — never a fake $0.00."""
    if not known or amount is None:
        return "price unknown"
    if abs(amount) < 0.00005:
        return "$0.00"
    if abs(amount) < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"


@dataclass
class ModelUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    latency_ms: float = 0.0
    requests: int = 0


@dataclass
class CostSnapshot:
    models: dict[str, ModelUsage] = field(default_factory=dict)
    model_usd: dict[str, float | None] = field(default_factory=dict)
    lines_added: int = 0
    lines_removed: int = 0
    api_ms: float = 0.0
    wall_ms: float = 0.0
    known_usd: float = 0.0
    unknown_models: list[str] = field(default_factory=list)
    requests: int = 0
    max_budget_usd: float | None = None

    @property
    def price_unknown(self) -> bool:
        return bool(self.unknown_models)

    @property
    def total_input_tokens(self) -> int:
        return sum(row.input_tokens for row in self.models.values())

    @property
    def total_output_tokens(self) -> int:
        return sum(row.output_tokens for row in self.models.values())

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(row.cache_read_tokens for row in self.models.values())

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(row.cache_creation_tokens for row in self.models.values())

    def total_label(self) -> str:
        known = format_usd(self.known_usd, known=True)
        if self.price_unknown:
            if self.known_usd > 0:
                return f"{known} + price unknown"
            return "price unknown"
        return known

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_usd": None if self.price_unknown and self.known_usd == 0 else self.known_usd,
            "total_label": self.total_label(),
            "price_unknown": self.price_unknown,
            "unknown_models": list(self.unknown_models),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cache_read_tokens": self.total_cache_read_tokens,
            "cache_creation_tokens": self.total_cache_creation_tokens,
            "api_ms": self.api_ms,
            "wall_ms": self.wall_ms,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "requests": self.requests,
            "max_budget_usd": self.max_budget_usd,
            "models": {
                name: {
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "cache_read_tokens": row.cache_read_tokens,
                    "cache_creation_tokens": row.cache_creation_tokens,
                    "latency_ms": row.latency_ms,
                    "requests": row.requests,
                    "usd": self.model_usd.get(name),
                    "price_known": name not in self.unknown_models,
                }
                for name, row in self.models.items()
            },
        }


class CostTracker:
    """Accumulate UsageUpdated events and file-diff line counts for one session."""

    def __init__(
        self,
        max_budget_usd: float | None = None,
        custom_prices: Mapping[str, Mapping[str, Any] | ModelPrice] | None = None,
    ) -> None:
        self.max_budget_usd = max_budget_usd
        self.custom_prices = dict(custom_prices or {})
        self._models: dict[str, ModelUsage] = {}
        self.lines_added = 0
        self.lines_removed = 0
        self._started = time.monotonic()

    @classmethod
    def from_config(cls, config: AgentConfig | None) -> CostTracker:
        if config is None:
            return cls()
        return cls(max_budget_usd=config.max_budget_usd, custom_prices=config.model_prices)

    def _price(self, model: str) -> ModelPrice:
        return lookup_price(model, self.custom_prices)

    def record_usage(self, event: UsageUpdated, fallback_model: str = "") -> None:
        model = (event.model or fallback_model or "unknown").strip() or "unknown"
        row = self._models.setdefault(model, ModelUsage(model=model))
        row.input_tokens += max(0, event.input_tokens)
        row.output_tokens += max(0, event.output_tokens)
        row.cache_read_tokens += max(0, event.cache_read_tokens)
        row.cache_creation_tokens += max(0, event.cache_creation_tokens)
        row.latency_ms += max(0.0, event.latency_ms)
        row.requests += 1

    def record_tool_result(self, tool_name: str, result: str) -> None:
        if tool_name not in _DIFF_TOOLS or not result:
            return
        added, removed = count_diff_lines(result)
        self.lines_added += added
        self.lines_removed += removed

    def restore_from_session(self, store: SessionStore) -> None:
        for event in store.iter_events():
            kind = event.get("type")
            payload = event.get("payload") or {}
            if kind == "usage_updated" and isinstance(payload, dict):
                self.record_usage(
                    UsageUpdated(
                        input_tokens=int(payload.get("input_tokens") or 0),
                        output_tokens=int(payload.get("output_tokens") or 0),
                        cache_read_tokens=int(payload.get("cache_read_tokens") or 0),
                        cache_creation_tokens=int(payload.get("cache_creation_tokens") or 0),
                        latency_ms=float(payload.get("latency_ms") or 0.0),
                        model=str(payload.get("model") or ""),
                    )
                )
            elif kind == "tool_result" and isinstance(payload, dict):
                self.record_tool_result(
                    str(payload.get("tool_name") or ""),
                    str(payload.get("result") or ""),
                )

    def snapshot(self) -> CostSnapshot:
        unknown: list[str] = []
        known_usd = 0.0
        models: dict[str, ModelUsage] = {}
        model_usd: dict[str, float | None] = {}
        api_ms = 0.0
        requests = 0
        for name, row in self._models.items():
            models[name] = ModelUsage(
                model=row.model,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                cache_read_tokens=row.cache_read_tokens,
                cache_creation_tokens=row.cache_creation_tokens,
                latency_ms=row.latency_ms,
                requests=row.requests,
            )
            api_ms += row.latency_ms
            requests += row.requests
            billed = cost_usd(
                billable_tokens(
                    row.input_tokens,
                    row.cache_read_tokens,
                    row.cache_creation_tokens,
                    name,
                ),
                row.output_tokens,
                self._price(name),
            )
            model_usd[name] = billed
            if billed is None:
                unknown.append(name)
            else:
                known_usd += billed
        return CostSnapshot(
            models=models,
            model_usd=model_usd,
            lines_added=self.lines_added,
            lines_removed=self.lines_removed,
            api_ms=api_ms,
            wall_ms=(time.monotonic() - self._started) * 1000.0,
            known_usd=known_usd,
            unknown_models=unknown,
            requests=requests,
            max_budget_usd=self.max_budget_usd,
        )

    def over_budget(self) -> bool:
        if self.max_budget_usd is None:
            return False
        return self.snapshot().known_usd >= self.max_budget_usd

    def budget_stop_text(self) -> str:
        snap = self.snapshot()
        spent = format_usd(snap.known_usd, known=True)
        cap = format_usd(self.max_budget_usd, known=self.max_budget_usd is not None)
        extra = ""
        if snap.price_unknown:
            extra = " (some models have unknown prices; budget uses known USD only)"
        return f"Stopped: session cost {spent} reached max_budget_usd {cap}.{extra}"


def render_cost_report(snapshot: CostSnapshot) -> str:
    """Plain-text `/cost` report. Unknown prices never print as $0.00."""
    if snapshot.requests == 0 and not snapshot.models:
        return "  No usage recorded in this session."
    lines = [
        f"  Total:        {snapshot.total_label()}",
        (
            f"  Tokens:       in {snapshot.total_input_tokens:,}  "
            f"out {snapshot.total_output_tokens:,}  "
            f"cache_read {snapshot.total_cache_read_tokens:,}  "
            f"cache_write {snapshot.total_cache_creation_tokens:,}"
        ),
        (
            f"  Duration:     API {snapshot.api_ms / 1000:.1f}s  "
            f"wall {snapshot.wall_ms / 1000:.1f}s"
        ),
        f"  Lines:        +{snapshot.lines_added} / -{snapshot.lines_removed}",
    ]
    if snapshot.max_budget_usd is not None:
        lines.append(f"  Budget:       {format_usd(snapshot.max_budget_usd, known=True)}")
    if snapshot.models:
        lines.append("")
        lines.append("  Per model:")
        for name, row in snapshot.models.items():
            billed = snapshot.model_usd.get(name)
            label = format_usd(billed, known=billed is not None)
            lines.append(
                f"    {name}: in {row.input_tokens:,}  out {row.output_tokens:,}  "
                f"cache_read {row.cache_read_tokens:,}  cache_write {row.cache_creation_tokens:,}  "
                f"{label}  ({row.requests} req, {row.latency_ms / 1000:.1f}s)"
            )
    return "\n".join(lines)
