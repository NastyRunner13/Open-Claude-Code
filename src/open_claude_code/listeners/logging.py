"""File-based logging listener — logs every agent event to a rotating log file."""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from open_claude_code.events import (
    EventBus,
    PostToolUse,
    PreToolUse,
    Stop,
    SubagentStart,
    SubagentStop,
    Thinking,
)

_DEFAULT_LOG_PATH = Path("occ.log")
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 3


def _build_logger(log_path: Path, level: int) -> logging.Logger:
    """Create/retrieve the occ.events logger with a RotatingFileHandler."""
    logger = logging.getLogger("occ.events")

    resolved = str(log_path.resolve())
    already = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and str(Path(h.baseFilename).resolve()) == resolved
        for h in logger.handlers
    )

    if not already:
        handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(levelname)-8s  %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger


def register_logging_listeners(
    event_bus: EventBus,
    log_path: Path | str = _DEFAULT_LOG_PATH,
    level: int = logging.DEBUG,
) -> logging.Logger:
    """Register file-logging handlers for every event type."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = _build_logger(log_path, level)
    logger.info("OCC logging started — writing to %s", log_path.resolve())

    async def on_thinking(event: Thinking) -> None:
        preview = event.text.strip().replace("\n", " ")[:120]
        logger.debug("[Thinking] %s", preview)

    async def on_pre_tool_use(event: PreToolUse) -> None:
        params = json.dumps(event.tool_params, separators=(",", ":"))
        logger.info("[PreToolUse] tool=%s params=%s", event.tool_name, params)

    async def on_post_tool_use(event: PostToolUse) -> None:
        preview = event.result.strip().replace("\n", " ")[:200]
        logger.info("[PostToolUse] tool=%s result=%s", event.tool_name, preview)

    async def on_stop(event: Stop) -> None:
        preview = event.text.strip().replace("\n", " ")[:200]
        logger.info("[Stop] response=%s", preview)

    async def on_subagent_start(event: SubagentStart) -> None:
        logger.info("[SubagentStart] task=%s", event.task)

    async def on_subagent_stop(event: SubagentStop) -> None:
        preview = event.result.strip().replace("\n", " ")[:200]
        logger.info("[SubagentStop] task=%s result=%s", event.task, preview)

    event_bus.on(Thinking, on_thinking)
    event_bus.on(PreToolUse, on_pre_tool_use)
    event_bus.on(PostToolUse, on_post_tool_use)
    event_bus.on(Stop, on_stop)
    event_bus.on(SubagentStart, on_subagent_start)
    event_bus.on(SubagentStop, on_subagent_stop)

    return logger
