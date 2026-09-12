"""XML/text tool-call recovery for OpenAI-compat hosts. No live API."""

from __future__ import annotations

import asyncio
import threading

from open_claude_code.providers.base import TextBlock, ToolUseBlock
from open_claude_code.providers.openai import OpenAIProvider
from open_claude_code.providers.tool_calls import apply_text_tool_recovery, recover_tool_calls

from tests.test_providers import _FakeStream, _bind_create, _completion, _delta_chunk

ECHO = {"echo"}
READ = {"read_file"}
ECHO_TOOL = [{"name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
READ_TOOL = [{
    "name": "read_file",
    "description": "Read",
    "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}},
}]


class TestRecoverToolCalls:
    def test_qwen_tool_call_json(self):
        text = (
            'I will read it.\n'
            '<tool_call>\n'
            '{"name": "read_file", "arguments": {"file_path": "README.md"}}\n'
            '</tool_call>'
        )
        calls, residual = recover_tool_calls(text, valid_names=READ)
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"file_path": "README.md"}
        assert "tool_call" not in residual
        assert "I will read it." in residual

    def test_opening_tag_optional(self):
        text = '{"name": "echo", "arguments": {"message": "hi"}}</tool_call>'
        calls, residual = recover_tool_calls(text, valid_names=ECHO)
        assert [c.name for c in calls] == ["echo"]
        assert calls[0].arguments == {"message": "hi"}
        assert residual == ""

    def test_glm_arg_key_value(self):
        text = (
            "<tool_call>read_file\n"
            "<arg_key>file_path</arg_key>\n"
            "<arg_value>src/main.py</arg_value>\n"
            "</tool_call>"
        )
        calls, _ = recover_tool_calls(text, valid_names=READ)
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"file_path": "src/main.py"}

    def test_glm_unclosed_arg_value(self):
        text = (
            "<tool_call>read_file\n"
            "<arg_key>file_path</arg_key>\n"
            "<arg_value>src/main.py\n"
            "</tool_call>"
        )
        calls, _ = recover_tool_calls(text, valid_names=READ)
        assert calls[0].arguments == {"file_path": "src/main.py"}

    def test_qwen3_function_eq(self):
        text = (
            "I'll list markdown files.\n"
            "<function=read_file>\n"
            "<parameter=file_path>\n"
            "README.md\n"
            "</parameter>\n"
            "</tool_call>"
        )
        calls, residual = recover_tool_calls(text, valid_names=READ)
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"file_path": "README.md"}
        assert "I'll list markdown files." in residual

    def test_invoke_xml(self):
        text = (
            '<invoke name="echo">\n'
            '<parameter name="message">ping</parameter>\n'
            "</invoke>"
        )
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].name == "echo"
        assert calls[0].arguments == {"message": "ping"}

    def test_bare_json_whole_message(self):
        text = '{"name": "echo", "arguments": {"message": "bare"}}'
        calls, residual = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].arguments == {"message": "bare"}
        assert residual == ""

    def test_bare_json_after_think(self):
        text = (
            "<think>need the file</think>\n"
            '{"name": "read_file", "arguments": {"file_path": "a.py"}}'
        )
        calls, _ = recover_tool_calls(text, valid_names=READ)
        assert calls[0].name == "read_file"

    def test_python_dict_arguments(self):
        text = "<tool_call>{'name': 'echo', 'arguments': {'message': 'py'}}</tool_call>"
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].arguments == {"message": "py"}

    def test_mistral_tool_calls(self):
        text = '[TOOL_CALLS][{"name": "echo", "arguments": {"message": "m"}}]'
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].name == "echo"
        assert calls[0].arguments == {"message": "m"}

    def test_python_tag(self):
        text = '<|python_tag|>{"name": "echo", "parameters": {"message": "llama"}}'
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].arguments == {"message": "llama"}

    def test_kimi_tokens(self):
        text = (
            "<|tool_call_begin|>functions.echo:0"
            "<|tool_call_argument_begin|>{\"message\": \"k\"}"
            "<|tool_call_end|>"
        )
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].name == "echo"
        assert calls[0].arguments == {"message": "k"}

    def test_mid_sentence_markup_is_ignored(self):
        text = 'you would emit <tool_call>{"name": "echo", "arguments": {"message": "x"}}</tool_call> here'
        calls, residual = recover_tool_calls(text, valid_names=ECHO)
        assert calls == []
        assert residual == text

    def test_unknown_name_is_not_executed(self):
        text = '<tool_call>{"name": "drop_table", "arguments": {}}</tool_call>'
        calls, residual = recover_tool_calls(text, valid_names=ECHO)
        assert calls == []
        assert "drop_table" not in residual

    def test_json_answer_is_not_a_tool_call(self):
        text = '{"result": 42, "ok": true}'
        calls, residual = recover_tool_calls(text, valid_names=ECHO)
        assert calls == []
        assert residual == text

    def test_no_fuzzy_name_repair(self):
        text = '<tool_call>{"name": "read", "arguments": {"file_path": "a.py"}}</tool_call>'
        calls, _ = recover_tool_calls(text, valid_names=READ)
        assert calls == []

    def test_parallel_tool_call_tags(self):
        text = (
            '<tool_call>{"name": "echo", "arguments": {"message": "one"}}</tool_call>\n'
            '<tool_call>{"name": "echo", "arguments": {"message": "two"}}</tool_call>'
        )
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert [c.arguments["message"] for c in calls] == ["one", "two"]

    def test_arguments_as_json_string(self):
        text = (
            '<tool_call>{"name": "echo", "arguments": "{\\"message\\": \\"s\\"}"}'
            "</tool_call>"
        )
        calls, _ = recover_tool_calls(text, valid_names=ECHO)
        assert calls[0].arguments == {"message": "s"}


class TestApplyTextToolRecovery:
    def test_lifts_text_into_tool_use_blocks(self):
        content = [TextBlock(text='<tool_call>{"name": "echo", "arguments": {"message": "hi"}}</tool_call>')]
        out = apply_text_tool_recovery(content, ECHO_TOOL)
        assert len(out) == 1
        assert isinstance(out[0], ToolUseBlock)
        assert out[0].name == "echo"
        assert out[0].id == "recovered_0"

    def test_skips_when_structured_calls_exist(self):
        content = [
            TextBlock(text='<tool_call>{"name": "echo", "arguments": {"message": "x"}}</tool_call>'),
            ToolUseBlock(id="call_1", name="echo", input={"message": "structured"}),
        ]
        out = apply_text_tool_recovery(content, ECHO_TOOL)
        assert out is content

    def test_skips_when_no_tools_were_sent(self):
        content = [TextBlock(text='{"name": "echo", "arguments": {"message": "x"}}')]
        out = apply_text_tool_recovery(content, [])
        assert out is content


def _start_xml_tool_server():
    """Native Ollama `/api/chat` mock: first turn is Qwen XML, second is prose."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    state = {"calls": 0, "saw_tool_result": False, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            state["requests"].append({"path": self.path, "body": body})
            messages = body.get("messages") or []
            saw_tool = any(m.get("role") == "tool" for m in messages)
            state["calls"] += 1
            state["saw_tool_result"] = state["saw_tool_result"] or saw_tool
            if saw_tool:
                text = "marker.txt contains the secret token OCC_RECOVERY_OK."
            else:
                text = (
                    "I'll read the file.\n"
                    '<tool_call>{"name": "read_file", '
                    '"arguments": {"file_path": "marker.txt"}}</tool_call>'
                )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            if body.get("stream", True):
                self.wfile.write(json.dumps({
                    "model": "qwen2.5-coder",
                    "message": {"role": "assistant", "content": text},
                    "done": False,
                }).encode() + b"\n")
                self.wfile.write(json.dumps({
                    "model": "qwen2.5-coder",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 8,
                    "eval_count": 12,
                    "total_duration": 1_000_000_000,
                }).encode() + b"\n")
                return
            payload = {
                "model": "qwen2.5-coder",
                "message": {"role": "assistant", "content": text},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 8,
                "eval_count": 12,
            }
            self.wfile.write(json.dumps(payload).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/v1", state


class TestOccExecRecoversXmlToolCall:
    def test_occ_exec_runs_recovered_read_file(self, tmp_path):
        import json
        import subprocess
        import sys

        (tmp_path / "marker.txt").write_text("secret token OCC_RECOVERY_OK\n", encoding="utf-8")
        (tmp_path / "occ.yml").write_text(
            "persist_sessions: false\npersist_snapshots: false\n",
            encoding="utf-8",
        )
        last_path = tmp_path / "last.txt"
        server, base_url, state = _start_xml_tool_server()
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "open_claude_code.main",
                    "--config", str(tmp_path / "occ.yml"),
                    "--model", "ollama/qwen2.5-coder",
                    "--base-url", base_url,
                    "--ephemeral",
                    "--json",
                    "--quiet",
                    "--output-last-message", str(last_path),
                    "exec",
                    "Read marker.txt using tools",
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
        finally:
            server.shutdown()

        assert result.returncode == 0, result.stderr + result.stdout
        final = last_path.read_text(encoding="utf-8")
        assert "OCC_RECOVERY_OK" in final
        assert "<tool_call>" not in final
        assert state["saw_tool_result"] is True
        assert state["calls"] >= 2
        assert state["requests"], "agent never hit the native chat endpoint"
        assert all(item["path"] == "/api/chat" for item in state["requests"])
        first = state["requests"][0]["body"]
        assert first["model"] == "qwen2.5-coder"
        assert first["options"]["num_ctx"] == 32768
        assert first["stream"] is True
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert any(e.get("type") == "final" for e in events)


class TestOpenAIProviderRecoversTextCalls:
    def test_send_recovers_qwen_markup(self):
        xml = '<tool_call>{"name": "echo", "arguments": {"message": "hi"}}</tool_call>'

        async def create(**kwargs):
            return _completion(xml)

        provider = _bind_create(OpenAIProvider(model="qwen2.5", api_key="test"), create)
        result = asyncio.run(provider.send([], ECHO_TOOL, "sys"))
        blocks = [b for b in result.content if isinstance(b, ToolUseBlock)]
        assert len(blocks) == 1
        assert blocks[0].name == "echo"
        assert blocks[0].input == {"message": "hi"}

    def test_send_does_not_recover_without_tools(self):
        xml = '<tool_call>{"name": "echo", "arguments": {"message": "hi"}}</tool_call>'

        async def create(**kwargs):
            return _completion(xml)

        provider = _bind_create(OpenAIProvider(model="qwen2.5", api_key="test"), create)
        result = asyncio.run(provider.send([], [], "sys"))
        assert isinstance(result.content[0], TextBlock)
        assert "tool_call" in result.content[0].text

    def test_stream_recovers_and_emits_tool_events(self):
        xml = '<tool_call>{"name": "echo", "arguments": {"message": "hi"}}</tool_call>'

        async def create(**kwargs):
            return _FakeStream([_delta_chunk(xml, finish="stop")])

        provider = _bind_create(OpenAIProvider(model="qwen2.5", api_key="test"), create)

        async def drain():
            events = []
            async for event in provider.stream([], ECHO_TOOL, "sys"):
                events.append(event)
            return events

        events = asyncio.run(drain())
        types = [e.type for e in events]
        assert "tool_use_start" in types
        assert "tool_use_end" in types
        done = events[-1]
        assert done.type == "done"
        assert done.response is not None
        blocks = [b for b in done.response.content if isinstance(b, ToolUseBlock)]
        assert blocks[0].name == "echo"
        assert blocks[0].input == {"message": "hi"}
