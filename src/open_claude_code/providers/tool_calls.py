"""Recover XML/text tool calls that local models dump into assistant content.

Qwen, GLM, Gemma, Mistral, and other Ollama/vLLM templates often narrate a
call as markup instead of filling `message.tool_calls`. The agent then treats
the turn as a final answer and stops. This module lifts those calls into
ToolUseBlock form when the structured field is empty.

Safety: framed markup must sit at a line start, names are never fuzzy-matched,
and recovery only executes names in the tool list that was sent this turn.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass

from .base import TextBlock, ToolUseBlock

_NAME_RE = re.compile(r"^[A-Za-z_][\w.-]{0,127}$")
_MAX_ARGS_BYTES = 16_384
_CALL_KEYS = frozenset({"name", "arguments", "parameters", "input", "id", "type"})

_TOOL_CALL_OPEN = re.compile(r"<tool_call\s*>", re.IGNORECASE)
_TOOL_CALL_CLOSE = re.compile(r"</tool_call\s*>", re.IGNORECASE)
_FUNCTION_EQ = re.compile(r"<function\s*=\s*([A-Za-z_][\w.-]*)\s*>", re.IGNORECASE)
_FUNCTION_ATTR = re.compile(
    r"<function\s+name\s*=\s*[\"']([A-Za-z_][\w.-]*)[\"']\s*>",
    re.IGNORECASE,
)
_FUNCTION_CLOSE = re.compile(r"</function\s*>", re.IGNORECASE)
_INVOKE_OPEN = re.compile(
    r"<invoke\s+name\s*=\s*[\"']([A-Za-z_][\w.-]*)[\"']\s*>",
    re.IGNORECASE,
)
_INVOKE_CLOSE = re.compile(r"</invoke\s*>", re.IGNORECASE)
_PARAM_EQ = re.compile(
    r"<parameter\s*=\s*([A-Za-z_][\w.-]*)\s*>\s*(.*?)\s*</parameter\s*>",
    re.DOTALL | re.IGNORECASE,
)
_PARAM_ATTR = re.compile(
    r"<parameter\s+name\s*=\s*[\"']([^\"']+)[\"']\s*>\s*(.*?)\s*</parameter\s*>",
    re.DOTALL | re.IGNORECASE,
)
_ARG_PAIR = re.compile(
    r"<arg_key\s*>\s*(.*?)\s*</arg_key\s*>\s*"
    r"<arg_value\s*>\s*(.*?)\s*(?:</arg_value\s*>|(?=<arg_key)|(?=</tool_call)|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_MISTRAL_MARK = re.compile(r"\[TOOL_CALLS\]", re.IGNORECASE)
_MISTRAL_NAMED = re.compile(
    r"\[TOOL_CALLS\]\s*([A-Za-z_][\w.-]*)\s*\[ARGS\]",
    re.IGNORECASE,
)
_PYTHON_TAG = "<|python_tag|>"
_KIMI_BEGIN = "<|tool_call_begin|>"
_KIMI_ARGS = "<|tool_call_argument_begin|>"
_KIMI_END = "<|tool_call_end|>"
_KIMI_NAME = re.compile(
    r"(?:functions\.)?([A-Za-z_][\w.-]*)(?::\d+)?",
)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class RecoveredCall:
    name: str
    arguments: dict


def recover_tool_calls(
    text: str,
    *,
    valid_names: set[str] | frozenset[str] | None = None,
) -> tuple[list[RecoveredCall], str]:
    """Parse assistant text for XML/text tool calls.

    Returns recovered calls (valid names only) and residual prose with
    framed markup removed. Unknown-name markup is stripped, not executed.
    """
    if not text:
        return [], text

    spans: list[tuple[int, int, RecoveredCall | None]] = []
    _scan_tool_call_tags(text, valid_names, spans)
    _scan_function_tags(text, valid_names, spans)
    _scan_invoke_tags(text, valid_names, spans)
    _scan_mistral(text, valid_names, spans)
    _scan_python_tag(text, valid_names, spans)
    _scan_kimi(text, valid_names, spans)
    _scan_orphan_closes(text, valid_names, spans)

    spans = _dedupe(spans)
    calls = [call for _, _, call in spans if call is not None]
    if not calls:
        bare = _bare_json_calls(text, valid_names)
        if bare:
            return bare, ""
        if spans:
            return [], _strip_spans(text, spans).strip()
        return [], text

    residual = _strip_spans(text, spans)
    return calls, residual.strip()


def apply_text_tool_recovery(
    content: list[TextBlock | ToolUseBlock],
    tools: list[dict],
) -> list[TextBlock | ToolUseBlock]:
    """If content is prose-only, lift recovered tool calls into ToolUseBlocks."""
    if not tools:
        return content
    if any(isinstance(block, ToolUseBlock) for block in content):
        return content
    text = "".join(block.text for block in content if isinstance(block, TextBlock))
    if not text:
        return content
    valid = {tool["name"] for tool in tools if "name" in tool}
    if not valid:
        return content
    calls, residual = recover_tool_calls(text, valid_names=valid)
    if not calls:
        return content
    recovered: list[TextBlock | ToolUseBlock] = []
    if residual:
        recovered.append(TextBlock(text=residual))
    for index, call in enumerate(calls):
        recovered.append(
            ToolUseBlock(
                id=f"recovered_{index}",
                name=call.name,
                input=call.arguments,
            )
        )
    return recovered


def _at_line_start(text: str, index: int) -> bool:
    while index > 0 and text[index - 1] in " \t":
        index -= 1
    return index == 0 or text[index - 1] == "\n"


def _accept_name(name: str, valid_names: set[str] | frozenset[str] | None) -> bool:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return False
    if valid_names is None:
        return True
    return name in valid_names


def _parse_args(raw) -> dict | None:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return {}
    if len(text.encode("utf-8")) > _MAX_ARGS_BYTES:
        return None
    parsed = _loads(text)
    return parsed if isinstance(parsed, dict) else None


def _loads(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None


def _value_at(text: str, start: int) -> tuple[object, int] | None:
    while start < len(text) and text[start] in " \t\r\n":
        start += 1
    if start >= len(text):
        return None
    try:
        obj, end = json.JSONDecoder().raw_decode(text, start)
        return obj, end
    except json.JSONDecodeError:
        pass
    if text[start] not in "{[":
        return None
    span = _balanced_span(text, start)
    if span is None:
        return None
    raw, end = span
    try:
        obj = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None
    return obj, end


def _balanced_span(text: str, start: int) -> tuple[str, int] | None:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escape = False
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
        else:
            if ch in "\"'":
                in_str = True
                quote = ch
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    raw = text[start : i + 1]
                    if len(raw.encode("utf-8")) > _MAX_ARGS_BYTES:
                        return None
                    return raw, i + 1
        i += 1
    return None


def _call_from_mapping(
    obj: object,
    valid_names: set[str] | frozenset[str] | None,
    *,
    strict_keys: bool = False,
) -> RecoveredCall | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if not isinstance(name, str):
        return None
    if strict_keys and set(obj) - _CALL_KEYS:
        return None
    if not _accept_name(name, valid_names):
        return None
    args = obj.get("arguments", obj.get("parameters", obj.get("input")))
    parsed = _parse_args(args)
    if parsed is None:
        return None
    return RecoveredCall(name=name, arguments=parsed)


def _call_from_name_and_args(
    name: str,
    args: object,
    valid_names: set[str] | frozenset[str] | None,
) -> RecoveredCall | None:
    if not _accept_name(name, valid_names):
        return None
    parsed = _parse_args(args)
    if parsed is None:
        return None
    return RecoveredCall(name=name, arguments=parsed)


def _xml_parameters(body: str) -> dict | None:
    pairs = _PARAM_EQ.findall(body) or _PARAM_ATTR.findall(body)
    if not pairs:
        value = _value_at(body, 0)
        if value is not None and isinstance(value[0], dict):
            return value[0]
        stripped = body.strip()
        if not stripped:
            return {}
        return None
    arguments: dict[str, object] = {}
    for key, raw in pairs:
        arguments[key] = _coerce_xml_value(raw)
    return arguments


def _coerce_xml_value(raw: str) -> object:
    text = raw.strip()
    if not text:
        return ""
    if text[:1] in "{[\"'" or text in {"true", "false", "null"} or text[:1].isdigit() or text[:1] == "-":
        loaded = _loads(text)
        if loaded is not None:
            return loaded
    return text


def _glm_arguments(body: str) -> dict | None:
    pairs = _ARG_PAIR.findall(body)
    if not pairs:
        return None
    return {key.strip(): _coerce_xml_value(value) for key, value in pairs}


def _close_after(pattern: re.Pattern[str], text: str, start: int, *extra: re.Pattern[str]) -> int | None:
    earliest: re.Match[str] | None = None
    for compiled in (pattern, *extra):
        match = compiled.search(text, start)
        if match and (earliest is None or match.start() < earliest.start()):
            earliest = match
    return earliest.end() if earliest else None


def _record(
    spans: list[tuple[int, int, RecoveredCall | None]],
    start: int,
    end: int,
    call: RecoveredCall | None,
    *,
    known_name: bool,
) -> None:
    if call is None and not known_name:
        return
    spans.append((start, end, call))


def _scan_tool_call_tags(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    for match in _TOOL_CALL_OPEN.finditer(text):
        if not _at_line_start(text, match.start()):
            continue
        close = _TOOL_CALL_CLOSE.search(text, match.end())
        if not close:
            continue
        body = text[match.end() : close.start()]
        call, known = _parse_tool_call_body(body, valid_names)
        _record(spans, match.start(), close.end(), call, known_name=known)


def _parse_tool_call_body(
    body: str,
    valid_names: set[str] | frozenset[str] | None,
) -> tuple[RecoveredCall | None, bool]:
    value = _value_at(body, 0)
    if value is not None:
        obj, end = value
        if isinstance(obj, list):
            # Parallel JSON array inside one tag: first call only at this
            # layer; _calls_from_json_value expands arrays at bare-json.
            if obj and isinstance(obj[0], dict):
                call = _call_from_mapping(obj[0], valid_names)
                return call, _mapping_name_known(obj[0], valid_names)
        call = _call_from_mapping(obj, valid_names)
        if call or _mapping_name_known(obj, valid_names):
            return call, True
        if body[end:].strip() == "" and isinstance(obj, dict) and "name" in obj:
            return None, True

    glm = _glm_arguments(body)
    name_match = re.match(r"\s*([A-Za-z_][\w.-]*)\b", body)
    if name_match and glm is not None:
        name = name_match.group(1)
        if not _NAME_RE.match(name):
            return None, False
        if valid_names is not None and name not in valid_names:
            return None, True
        return RecoveredCall(name=name, arguments=glm), True

    if name_match:
        name = name_match.group(1)
        rest = body[name_match.end() :]
        value = _value_at(rest, 0)
        if value is not None and isinstance(value[0], dict):
            if valid_names is not None and name not in valid_names:
                return None, _NAME_RE.match(name) is not None
            parsed = value[0]
            if "name" in parsed:
                call = _call_from_mapping(parsed, valid_names)
                return call, True
            if _accept_name(name, valid_names):
                return RecoveredCall(name=name, arguments=parsed), True
            return None, _NAME_RE.match(name) is not None
    return None, False


def _mapping_name_known(obj: object, valid_names: set[str] | frozenset[str] | None) -> bool:
    if not isinstance(obj, dict):
        return False
    name = obj.get("name")
    return isinstance(name, str) and _NAME_RE.match(name) is not None


def _scan_function_tags(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    for compiled in (_FUNCTION_EQ, _FUNCTION_ATTR):
        for match in compiled.finditer(text):
            if not _at_line_start(text, match.start()):
                continue
            end = _close_after(_FUNCTION_CLOSE, text, match.end(), _TOOL_CALL_CLOSE)
            if end is None:
                continue
            name = match.group(1)
            close = _FUNCTION_CLOSE.search(text, match.end()) or _TOOL_CALL_CLOSE.search(
                text, match.end()
            )
            body = text[match.end() : close.start()] if close else text[match.end() : end]
            args = _xml_parameters(body)
            if args is None:
                continue
            call = (
                RecoveredCall(name=name, arguments=args)
                if _accept_name(name, valid_names)
                else None
            )
            _record(
                spans,
                match.start(),
                end,
                call,
                known_name=_NAME_RE.match(name) is not None,
            )


def _scan_invoke_tags(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    for match in _INVOKE_OPEN.finditer(text):
        if not _at_line_start(text, match.start()):
            continue
        close = _INVOKE_CLOSE.search(text, match.end())
        if not close:
            continue
        name = match.group(1)
        args = _xml_parameters(text[match.end() : close.start()])
        call = None
        known = _NAME_RE.match(name) is not None
        if args is not None and _accept_name(name, valid_names):
            call = RecoveredCall(name=name, arguments=args)
        _record(
            spans,
            match.start(),
            close.end(),
            call,
            known_name=known and args is not None,
        )


def _scan_mistral(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    for match in _MISTRAL_NAMED.finditer(text):
        if not _at_line_start(text, match.start()):
            continue
        value = _value_at(text, match.end())
        if value is None or not isinstance(value[0], dict):
            continue
        name = match.group(1)
        call = _call_from_name_and_args(name, value[0], valid_names)
        known = _NAME_RE.match(name) is not None
        _record(spans, match.start(), value[1], call, known_name=known)

    for match in _MISTRAL_MARK.finditer(text):
        if not _at_line_start(text, match.start()):
            continue
        if any(start <= match.start() < end for start, end, _ in spans):
            continue
        value = _value_at(text, match.end())
        if value is None:
            continue
        obj, end = value
        extracted = _calls_from_json_value(obj, valid_names)
        if not extracted:
            if isinstance(obj, dict) and isinstance(obj.get("name"), str):
                _record(spans, match.start(), end, None, known_name=True)
            continue
        # One span covering the whole [TOOL_CALLS] payload; extra calls
        # are attached as zero-width follow-ups so residual stripping
        # still removes one region.
        _record(spans, match.start(), end, extracted[0], known_name=True)
        for extra in extracted[1:]:
            spans.append((end, end, extra))


def _scan_python_tag(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    start = 0
    while True:
        index = text.find(_PYTHON_TAG, start)
        if index < 0:
            return
        if _at_line_start(text, index):
            value = _value_at(text, index + len(_PYTHON_TAG))
            if value is not None:
                obj, end = value
                call = _call_from_mapping(obj, valid_names)
                known = _mapping_name_known(obj, valid_names)
                _record(spans, index, end, call, known_name=known)
        start = index + len(_PYTHON_TAG)


def _scan_kimi(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    start = 0
    while True:
        index = text.find(_KIMI_BEGIN, start)
        if index < 0:
            return
        if _at_line_start(text, index):
            args_at = text.find(_KIMI_ARGS, index)
            end_at = text.find(_KIMI_END, index)
            if args_at > index and end_at > args_at:
                name_raw = text[index + len(_KIMI_BEGIN) : args_at].strip()
                name_match = _KIMI_NAME.search(name_raw)
                value = _value_at(text, args_at + len(_KIMI_ARGS))
                if name_match and value is not None:
                    call = _call_from_name_and_args(
                        name_match.group(1), value[0], valid_names
                    )
                    known = _NAME_RE.match(name_match.group(1)) is not None
                    close_end = end_at + len(_KIMI_END)
                    _record(spans, index, close_end, call, known_name=known)
        start = index + len(_KIMI_BEGIN)


def _scan_orphan_closes(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> None:
    """Quantized Qwen often emits `{...}</tool_call>` with no opening tag."""
    for match in _TOOL_CALL_CLOSE.finditer(text):
        if any(start <= match.start() < end for start, end, _ in spans):
            continue
        obj_hit = _json_ending_before(text, match.start())
        if obj_hit is None:
            continue
        obj, obj_start = obj_hit
        if not _at_line_start(text, obj_start):
            continue
        call = _call_from_mapping(obj, valid_names)
        known = _mapping_name_known(obj, valid_names)
        _record(spans, obj_start, match.end(), call, known_name=known)


def _json_ending_before(text: str, end: int) -> tuple[dict, int] | None:
    window_start = max(0, end - _MAX_ARGS_BYTES)
    cursor = text.rfind("{", window_start, end)
    while cursor != -1:
        value = _value_at(text, cursor)
        if value is not None and isinstance(value[0], dict):
            obj, obj_end = value
            if text[obj_end:end].strip() == "":
                return obj, cursor
        cursor = text.rfind("{", window_start, cursor)
    return None


def _calls_from_json_value(
    obj: object,
    valid_names: set[str] | frozenset[str] | None,
) -> list[RecoveredCall]:
    if isinstance(obj, list):
        calls = []
        for item in obj:
            call = _call_from_mapping(item, valid_names, strict_keys=True)
            if call:
                calls.append(call)
        return calls
    call = _call_from_mapping(obj, valid_names, strict_keys=True)
    return [call] if call else []


def _bare_json_calls(
    text: str,
    valid_names: set[str] | frozenset[str] | None,
) -> list[RecoveredCall]:
    stripped = _THINK_BLOCK.sub("", text).strip()
    if stripped.startswith("</think>"):
        stripped = stripped[len("</think>") :].strip()
    if not stripped or stripped[0] not in "{[":
        return []
    value = _value_at(stripped, 0)
    if value is None:
        return []
    obj, end = value
    if stripped[end:].strip():
        return []
    return _calls_from_json_value(obj, valid_names)


def _dedupe(
    spans: list[tuple[int, int, RecoveredCall | None]],
) -> list[tuple[int, int, RecoveredCall | None]]:
    ordered = sorted(spans, key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, RecoveredCall | None]] = []
    for start, end, call in ordered:
        if start == end and call is not None:
            kept.append((start, end, call))
            continue
        if any(not (end <= ks or start >= ke) for ks, ke, _ in kept if ks != ke):
            continue
        kept.append((start, end, call))
    return kept


def _strip_spans(text: str, spans: list[tuple[int, int, RecoveredCall | None]]) -> str:
    cut = sorted({(start, end) for start, end, _ in spans if start != end})
    pieces: list[str] = []
    cursor = 0
    for start, end in cut:
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    residual = "".join(pieces)
    residual = re.sub(r"\n{3,}", "\n\n", residual)
    return residual
