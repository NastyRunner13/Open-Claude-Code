"""Append-only, local storage for reproducible OCC sessions.

Each session has a small metadata JSON document and a JSONL event ledger.  The
ledger is intentionally simple: it remains readable without OCC and can later
be exported as a full task capsule.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from open_claude_code.config import AgentConfig


FORMAT_VERSION = 1
_SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "password", "secret", "token")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _session_root(path: str | Path, cwd: str | Path | None = None) -> Path:
    root = Path(path).expanduser()
    if not root.is_absolute():
        root = Path(cwd or Path.cwd()) / root
    return root.resolve(strict=False)


def _json_value(value: Any) -> Any:
    """Convert the small set of runtime values we persist into JSON values."""
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _redact(value: Any, key: str = "") -> Any:
    """Redact config values whose keys indicate credentials before persistence."""
    if any(part in key.lower() for part in _SENSITIVE_KEY_PARTS):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(name): _redact(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value


def _config_snapshot(config: "AgentConfig | None") -> tuple[dict[str, Any], str]:
    raw = asdict(config) if config is not None else {}
    snapshot = _redact(_json_value(raw))
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SessionStore:
    """Persist a session's messages and execution evidence to local JSON/JSONL."""

    def __init__(self, root: Path, session_id: str, metadata: dict[str, Any]) -> None:
        self.root = root
        self.session_id = session_id
        self.metadata_path = self.root / f"{session_id}.json"
        self.transcript_path = self.root / f"{session_id}.jsonl"
        self._metadata = metadata

    @classmethod
    def create(
        cls,
        config: "AgentConfig | None",
        model: str,
        mode: str,
        cwd: str | Path | None = None,
        parent_session_id: str = "",
    ) -> "SessionStore":
        """Create a new durable session and emit its first ledger entry."""
        root = _session_root(config.sessions_dir if config else ".occ/sessions", cwd)
        root.mkdir(parents=True, exist_ok=True)
        session_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        snapshot, config_hash = _config_snapshot(config)
        now = _now()
        metadata = {
            "format_version": FORMAT_VERSION,
            "session_id": session_id,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "cwd": str(Path(cwd or Path.cwd()).resolve()),
            "model": model,
            "mode": mode,
            "config": snapshot,
            "config_hash": config_hash,
            "resume_count": 0,
            "title": "",
            "parent_session_id": parent_session_id,
        }
        store = cls(root, session_id, metadata)
        store._write_metadata()
        store.record("session_started", {"resumed": False})
        return store

    @classmethod
    def resume(
        cls,
        session_id: str,
        config: "AgentConfig | None" = None,
        cwd: str | Path | None = None,
    ) -> "SessionStore":
        """Open an existing session for appending and preserve its original metadata."""
        if Path(session_id).name != session_id or not session_id:
            raise ValueError("session id must be a plain session filename")
        root = _session_root(config.sessions_dir if config else ".occ/sessions", cwd)
        metadata_path = root / f"{session_id}.json"
        transcript_path = root / f"{session_id}.jsonl"
        if not metadata_path.is_file() or not transcript_path.is_file():
            raise FileNotFoundError(f"session '{session_id}' was not found in {root}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        store = cls(root, session_id, metadata)
        store._metadata["status"] = "active"
        store._metadata["updated_at"] = _now()
        store._metadata["resume_count"] = int(store._metadata.get("resume_count", 0)) + 1
        store._write_metadata()
        store.record("session_resumed", {"resume_count": store._metadata["resume_count"]})
        return store

    @classmethod
    def list_sessions(
        cls,
        config: "AgentConfig | None" = None,
        cwd: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return compact metadata for every readable local session, newest first."""
        root = _session_root(config.sessions_dir if config else ".occ/sessions", cwd)
        if not root.is_dir():
            return []

        sessions: list[dict[str, Any]] = []
        for metadata_path in root.glob("*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict) and metadata.get("session_id"):
                sessions.append(metadata)
        return sorted(sessions, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    @property
    def metadata(self) -> dict[str, Any]:
        """A copy of the session metadata suitable for display."""
        return dict(self._metadata)

    def record(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Append one timestamped event to the JSONL ledger."""
        entry = {
            "timestamp": _now(),
            "type": event_type,
            "payload": _json_value(payload or {}),
        }
        with self.transcript_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        self._metadata["updated_at"] = entry["timestamp"]
        self._write_metadata()

    def record_history(self, message: dict[str, Any]) -> None:
        """Record an exact history item so the session can later be resumed."""
        self.record("history_append", {"message": message})

    def record_tool_call(
        self,
        tool_name: str,
        tool_use_id: str,
        tool_params: dict[str, Any],
        approved: bool,
        reason: str = "",
    ) -> None:
        self.record(
            "tool_call",
            {
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "tool_params": tool_params,
                "approved": approved,
                "reason": reason,
            },
        )

    def record_tool_result(self, tool_name: str, tool_use_id: str, result: Any) -> None:
        self.record(
            "tool_result",
            {
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "result": result,
            },
        )

    def iter_events(self) -> Iterator[dict[str, Any]]:
        """Yield each JSONL ledger object. Malformed lines are skipped."""
        if not self.transcript_path.is_file():
            return
        with self.transcript_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    yield event

    def load_history(self) -> list[dict[str, Any]]:
        """Reconstruct the model history from the append-only ledger."""
        history: list[dict[str, Any]] = []
        with self.transcript_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                    message = entry.get("payload", {}).get("message")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if entry.get("type") == "history_append" and isinstance(message, dict):
                    history.append(message)
        return history

    def close(self) -> None:
        """Mark the session closed without deleting any execution evidence."""
        if self._metadata.get("status") == "closed":
            return
        self.record("session_closed", {})
        self._metadata["status"] = "closed"
        self._metadata["updated_at"] = _now()
        self._write_metadata()

    def rename(self, title: str) -> None:
        """Give the session a human-readable title without changing its ID."""
        clean = title.strip()
        if not clean:
            raise ValueError("session title cannot be empty")
        self._metadata["title"] = clean[:200]
        self._metadata["updated_at"] = _now()
        self._write_metadata()
        self.record("session_renamed", {"title": self._metadata["title"]})

    def export(self, path: str | Path) -> Path:
        """Export a reproducible task capsule containing metadata and ledger."""
        destination = Path(path).expanduser().resolve(strict=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        events: list[dict[str, Any]] = []
        if self.transcript_path.is_file():
            for line in self.transcript_path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except json.JSONDecodeError:
                    continue
        capsule = {"format_version": FORMAT_VERSION, "metadata": self.metadata, "events": events}
        destination.write_text(json.dumps(capsule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.record("session_exported", {"path": str(destination)})
        return destination

    def _write_metadata(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary_path = self.metadata_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(self._metadata, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.metadata_path)
