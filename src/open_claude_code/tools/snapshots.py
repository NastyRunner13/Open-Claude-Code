"""Durable, local snapshots used to make file edits reversible."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class FileSnapshot:
    """One before-change snapshot of a workspace file."""

    snapshot_id: str
    file_path: Path
    existed: bool
    content_path: Path | None
    mode: int | None
    created_at: str


class SnapshotStore:
    """Append-only snapshot store scoped to one OCC session.

    Binary content lives in individual files rather than JSONL, so snapshots
    preserve arbitrary text encodings and remain cheap to inspect or remove.
    """

    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root.resolve(strict=False) / session_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"

    def create(self, file_path: str | Path) -> FileSnapshot:
        """Capture the current state of ``file_path`` before it is changed."""
        path = Path(file_path).resolve(strict=False)
        snapshot_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}"
        existed = path.is_file()
        content_path: Path | None = None
        mode: int | None = None

        if existed:
            content_path = self.root / f"{snapshot_id}.bin"
            content_path.write_bytes(path.read_bytes())
            mode = path.stat().st_mode

        snapshot = FileSnapshot(
            snapshot_id=snapshot_id,
            file_path=path,
            existed=existed,
            content_path=content_path,
            mode=mode,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._append(snapshot)
        return snapshot

    def restore(self, snapshot_id: str) -> FileSnapshot:
        """Restore one snapshot and return its metadata.

        A snapshot of a file that did not previously exist removes the file,
        making creates just as reversible as overwrites.
        """
        snapshot = self.get(snapshot_id)
        if snapshot is None:
            raise KeyError(f"snapshot '{snapshot_id}' was not found")

        target = snapshot.file_path
        if snapshot.existed:
            assert snapshot.content_path is not None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(snapshot.content_path.read_bytes())
            if snapshot.mode is not None:
                os.chmod(target, snapshot.mode)
        elif target.exists():
            if target.is_dir():
                raise IsADirectoryError(f"cannot undo file snapshot over directory: {target}")
            target.unlink()
        return snapshot

    def latest_for(self, file_path: str | Path) -> FileSnapshot | None:
        target = Path(file_path).resolve(strict=False)
        for snapshot in reversed(self._all()):
            if snapshot.file_path == target:
                return snapshot
        return None

    def get(self, snapshot_id: str) -> FileSnapshot | None:
        for snapshot in self._all():
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        return None

    def _all(self) -> list[FileSnapshot]:
        if not self.index_path.is_file():
            return []
        snapshots: list[FileSnapshot] = []
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                snapshots.append(
                    FileSnapshot(
                        snapshot_id=item["snapshot_id"],
                        file_path=Path(item["file_path"]),
                        existed=bool(item["existed"]),
                        content_path=(Path(item["content_path"]) if item.get("content_path") else None),
                        mode=item.get("mode"),
                        created_at=item["created_at"],
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return snapshots

    def _append(self, snapshot: FileSnapshot) -> None:
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "file_path": str(snapshot.file_path),
            "existed": snapshot.existed,
            "content_path": str(snapshot.content_path) if snapshot.content_path else None,
            "mode": snapshot.mode,
            "created_at": snapshot.created_at,
        }
        with self.index_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
