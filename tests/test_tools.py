"""Tests for tool functions."""

import asyncio
import os

import pytest

from open_claude_code.tools.edit_file import edit_file
from open_claude_code.tools.find_files import find_files
from open_claude_code.tools.list_directory import list_directory
from open_claude_code.tools.read_file import read_file
from open_claude_code.tools.run_shell import run_shell
from open_claude_code.tools.sandbox import sandbox
from open_claude_code.tools.write_file import write_file


class TestReadFile:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        result = asyncio.run(read_file(str(f)))
        assert str(result) == "hello world"

    def test_returns_error_for_missing_file(self, tmp_path):
        result = asyncio.run(read_file(str(tmp_path / "nope.txt")))
        assert result.success is False

    def test_truncates_large_output(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 20000)
        result = asyncio.run(read_file(str(f)))
        assert len(str(result)) <= 10100
        assert str(result).endswith("[truncated]")


class TestWriteFile:
    def test_writes_file(self, tmp_path):
        f = tmp_path / "out.txt"
        result = asyncio.run(write_file(str(f), "hello"))
        assert result.success is True
        assert f.read_text() == "hello"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "a" / "b" / "out.txt"
        result = asyncio.run(write_file(str(f), "nested"))
        assert result.success is True
        assert f.read_text() == "nested"


class TestEditFile:
    def test_replaces_unique_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = asyncio.run(edit_file(str(f), "hello", "goodbye"))
        assert result.success is True
        assert f.read_text() == "goodbye world"

    def test_fails_on_missing_string(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = asyncio.run(edit_file(str(f), "nope", "goodbye"))
        assert result.success is False
        assert "not found" in str(result)

    def test_fails_on_ambiguous_match(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("aaa aaa")
        result = asyncio.run(edit_file(str(f), "aaa", "bbb"))
        assert result.success is False
        assert "not unique" in str(result)


class TestListDirectory:
    def test_lists_entries(self, tmp_path):
        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()
        result = asyncio.run(list_directory(str(tmp_path)))
        output = str(result)
        assert "file.txt" in output
        assert "subdir/" in output

    def test_handles_missing_directory(self):
        result = asyncio.run(list_directory("/tmp/does_not_exist_xyz_occ"))
        assert result.success is False


class TestFindFiles:
    def test_finds_matching_files(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "c.txt").touch()
        result = asyncio.run(find_files("*.py", str(tmp_path)))
        output = str(result)
        assert "a.py" in output
        assert "b.py" in output
        assert "c.txt" not in output

    def test_returns_message_for_no_matches(self, tmp_path):
        result = asyncio.run(find_files("*.xyz", str(tmp_path)))
        assert "No files found" in str(result)


class TestRunShell:
    def test_runs_echo(self):
        result = asyncio.run(run_shell("echo hello"))
        output = str(result)
        assert "Exit code: 0" in output
        assert "hello" in output

    def test_failing_command(self):
        if os.name == "nt":
            result = asyncio.run(run_shell("exit /b 1"))
        else:
            result = asyncio.run(run_shell("exit 1"))
        assert result.success is False
        assert result.metadata.get("exit_code") == 1


class TestSandbox:
    def test_runs_python_code(self):
        result = asyncio.run(sandbox("print('hello from sandbox')"))
        output = str(result)
        assert "Exit code: 0" in output
        assert "hello from sandbox" in output

    def test_handles_error(self):
        result = asyncio.run(sandbox("raise ValueError('test error')"))
        assert result.success is False
        assert result.metadata.get("exit_code") == 1
        assert "ValueError" in str(result.data)

    def test_unsupported_language(self):
        result = asyncio.run(sandbox("code", language="rust"))
        assert result.success is False
        assert "unsupported language" in str(result)
