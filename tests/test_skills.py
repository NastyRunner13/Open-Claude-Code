"""Tests for the skills system."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from open_claude_code.agent import Agent
from open_claude_code.config import AgentConfig
from open_claude_code.events import EventBus, ToolDenied
from open_claude_code.middleware import MiddlewareManager
from open_claude_code.middleware.skills import SkillsMiddleware
from open_claude_code.providers.base import ToolUseBlock
from open_claude_code.skills.loader import Skill, SkillManager, parse_skill_md
from open_claude_code.tools.load_skill import load_skill

from tests.fakes import ScriptedProvider, ScriptedTurn


def _write_skill(root: Path, dirname: str, frontmatter: str, body: str = "Do it") -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


class TestParseSkillMd:
    def test_parses_frontmatter(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: My Skill\n"
            "description: Does cool stuff\n"
            "---\n"
            "Follow these instructions:\n"
            "1. Do this\n"
            "2. Do that\n"
        )

        skill = parse_skill_md(skill_md)
        assert skill.name == "My Skill"
        assert skill.description == "Does cool stuff"
        assert "Follow these instructions" in skill.instructions
        assert "1. Do this" in skill.instructions

    def test_no_frontmatter(self, tmp_path):
        skill_dir = tmp_path / "plain"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("Just plain instructions here.")

        skill = parse_skill_md(skill_md)
        assert skill.name == "unnamed"
        assert "Just plain instructions" in skill.instructions

    def test_discovers_scripts(self, tmp_path):
        skill_dir = tmp_path / "scripted"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: Scripted\ndescription: Has scripts\n---\nDo stuff")
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.py").touch()
        (scripts_dir / "util.sh").touch()

        skill = parse_skill_md(skill_dir / "SKILL.md")
        assert len(skill.scripts) == 2


class TestSkillManager:
    def test_discovers_skills(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Test Skill\ndescription: A test\n---\nInstructions"
        )

        sm = SkillManager(search_dirs=[str(skills_dir)])
        assert "Test Skill" in sm.available

    def test_load_and_unload(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: My Skill\ndescription: Desc\n---\nDo things"
        )

        sm = SkillManager(search_dirs=[str(skills_dir)])

        # Not loaded initially
        assert "My Skill" not in sm.loaded

        # Load
        skill = sm.load("My Skill")
        assert skill is not None
        assert skill.name == "My Skill"
        assert "My Skill" in sm.loaded

        # Loading again returns same
        skill2 = sm.load("My Skill")
        assert skill2 is skill

        # Unload
        assert sm.unload("My Skill") is True
        assert "My Skill" not in sm.loaded
        assert sm.unload("My Skill") is False

    def test_prompt_injection(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        skill_dir = skills_dir / "helper"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Helper\ndescription: Helps\n---\nStep 1: help"
        )

        sm = SkillManager(search_dirs=[str(skills_dir)])

        # No prompt additions when no skills loaded
        assert sm.get_prompt_additions() == ""

        # Load and check injection
        sm.load("Helper")
        additions = sm.get_prompt_additions()
        assert "Helper" in additions
        assert "Step 1: help" in additions

    def test_empty_directory(self, tmp_path):
        sm = SkillManager(search_dirs=[str(tmp_path / "nonexistent")])
        assert len(sm.available) == 0

    def test_list_formatted_no_skills(self, tmp_path):
        sm = SkillManager(search_dirs=[str(tmp_path / "empty")])
        result = sm.list_formatted()
        assert "No skills found" in result

    def test_list_formatted_with_skills(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_dir = skills_dir / "s1"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: Alpha\ndescription: First\n---\nContent")

        sm = SkillManager(search_dirs=[str(skills_dir)])
        result = sm.list_formatted()
        assert "Alpha" in result
        assert "First" in result

    def test_load_from_path(self, tmp_path):
        skill_dir = tmp_path / "direct-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Direct\ndescription: Loaded by path\n---\nContent"
        )

        sm = SkillManager(search_dirs=[])
        skill = sm.load(str(skill_dir))
        assert skill is not None
        assert skill.name == "Direct"

    def test_rescan(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        sm = SkillManager(search_dirs=[str(skills_dir)])
        assert len(sm.available) == 0

        # Add a skill after initial scan
        skill_dir = skills_dir / "new-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: New\ndescription: Fresh\n---\nContent")

        sm.rescan()
        assert "New" in sm.available


class TestSkillPromptInjection:
    def test_prompt_format(self):
        skill = Skill(
            name="Test",
            description="A test skill",
            instructions="Do the thing",
            path=Path("/tmp"),
        )
        injection = skill.prompt_injection
        assert "## Skill: Test" in injection
        assert "A test skill" in injection
        assert "Do the thing" in injection


class TestAllowedToolsAndBundledFiles:
    def test_parses_allowed_tools_list(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "narrow",
            "name: Narrow\ndescription: Reads\nallowed_tools:\n  - read_file\n  - grep_search",
        )
        skill = parse_skill_md(skill_dir / "SKILL.md")
        assert skill.allowed_tools == ["read_file", "grep_search"]

    def test_parses_hyphenated_and_string_allowed_tools(self, tmp_path):
        hyphen = _write_skill(
            tmp_path,
            "hyphen",
            "name: Hyphen\ndescription: d\nallowed-tools: read_file, grep_search",
        )
        skill = parse_skill_md(hyphen / "SKILL.md")
        assert skill.allowed_tools == ["read_file", "grep_search"]

    def test_prompt_lists_bundled_files_and_allowed_tools(self, tmp_path):
        skill_dir = _write_skill(
            tmp_path,
            "pack",
            "name: Pack\ndescription: Has files\nallowed_tools:\n  - read_file\n  - run_shell",
            "Use the helper.",
        )
        (skill_dir / "scripts").mkdir()
        (skill_dir / "examples").mkdir()
        (skill_dir / "assets").mkdir()
        helper = skill_dir / "scripts" / "helper.py"
        example = skill_dir / "examples" / "sample.txt"
        asset = skill_dir / "assets" / "template.md"
        helper.write_text("print('hi')\n", encoding="utf-8")
        example.write_text("example\n", encoding="utf-8")
        asset.write_text("# tmpl\n", encoding="utf-8")
        (skill_dir / "scripts" / ".hidden").write_text("nope\n", encoding="utf-8")
        (skill_dir / "scripts" / "subdir").mkdir()

        skill = parse_skill_md(skill_dir / "SKILL.md")
        assert skill.scripts == [helper.resolve()]
        assert skill.examples == [example.resolve()]
        assert skill.assets == [asset.resolve()]
        injection = skill.prompt_injection
        assert str(helper.resolve()) in injection
        assert str(example.resolve()) in injection
        assert str(asset.resolve()) in injection
        assert "do not assume they have already been executed" in injection
        assert "narrows available tools to: read_file, run_shell" in injection
        assert ".hidden" not in injection

    def test_malformed_skill_is_logged_not_silently_skipped(self, tmp_path, caplog):
        skills = tmp_path / "skills"
        broken = skills / "broken"
        broken.mkdir(parents=True)
        (broken / "SKILL.md").write_bytes(b"\xff\xfe not utf-8")
        with caplog.at_level(logging.WARNING, logger="occ.skills"):
            sm = SkillManager(search_dirs=[str(skills)])
        assert sm.available == {}
        assert sm.scan_warnings
        assert "malformed" in caplog.text.lower()
        listing = sm.list_formatted()
        assert "Skipped:" in listing

    def test_invalid_yaml_frontmatter_is_logged(self, tmp_path, caplog):
        skill_dir = tmp_path / "bad-yaml"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: [unterminated\n---\nStill a body\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="occ.skills"):
            skill = parse_skill_md(skill_dir / "SKILL.md")
        assert skill.name == "unnamed"
        assert "Still a body" in skill.instructions
        assert "invalid YAML" in caplog.text

    def test_restriction_is_intersection_and_supports_globs(self, tmp_path):
        root = tmp_path / "skills"
        _write_skill(
            root,
            "a",
            "name: A\ndescription: a\nallowed_tools:\n  - read_*\n  - write_file",
        )
        _write_skill(
            root,
            "b",
            "name: B\ndescription: b\nallowed_tools:\n  - read_file\n  - grep_search",
        )
        sm = SkillManager(search_dirs=[str(root)])
        assert sm.tool_permitted("write_file") is True
        sm.load("A")
        assert sm.tool_permitted("read_file") is True
        assert sm.tool_permitted("read_url") is True
        assert sm.tool_permitted("write_file") is True
        assert sm.tool_permitted("grep_search") is False
        sm.load("B")
        assert sm.tool_permitted("read_file") is True
        assert sm.tool_permitted("read_url") is False
        assert sm.tool_permitted("write_file") is False
        reason = sm.restriction_reason("write_file")
        assert reason is not None
        assert "write_file" in reason
        assert "B:" in reason
        sm.unload("A")
        sm.unload("B")
        assert sm.tool_permitted("write_file") is True

    def test_empty_allowed_tools_does_not_restrict(self, tmp_path):
        root = tmp_path / "skills"
        _write_skill(root, "open", "name: Open\ndescription: none")
        sm = SkillManager(search_dirs=[str(root)])
        sm.load("Open")
        assert sm.tool_permitted("write_file") is True
        schemas = [{"name": "write_file"}, {"name": "read_file"}]
        assert sm.filter_tool_schemas(schemas) == schemas

    def test_filter_tool_schemas_drops_disallowed(self, tmp_path):
        root = tmp_path / "skills"
        _write_skill(
            root,
            "n",
            "name: N\ndescription: n\nallowed_tools:\n  - read_file",
        )
        sm = SkillManager(search_dirs=[str(root)])
        sm.load("N")
        schemas = [{"name": "read_file"}, {"name": "write_file"}, {"name": "load_skill"}]
        names = [item["name"] for item in sm.filter_tool_schemas(schemas)]
        assert names == ["read_file"]

    def test_catalog_and_list_mention_allowed_tools(self, tmp_path):
        root = tmp_path / "skills"
        _write_skill(
            root,
            "n",
            "name: N\ndescription: Reads files\nallowed_tools:\n  - read_file",
        )
        sm = SkillManager(search_dirs=[str(root)])
        assert "narrows tools to read_file" in sm.get_catalog_prompt()
        assert "tools: read_file" in sm.list_formatted()

    @pytest.mark.asyncio
    async def test_load_skill_result_mentions_tools_and_scripts(self, tmp_path):
        root = tmp_path / "skills"
        skill_dir = _write_skill(
            root,
            "pack",
            "name: Pack\ndescription: Packed\nallowed_tools:\n  - read_file",
        )
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        helper = scripts / "helper.py"
        helper.write_text("print(1)\n", encoding="utf-8")
        sm = SkillManager(search_dirs=[str(root)])
        result = await load_skill("Pack", _skill_manager=sm)
        assert result.success is True
        text = str(result)
        assert "narrowed to: read_file" in text
        assert str(helper.resolve()) in text
        assert result.metadata["allowed_tools"] == ["read_file"]

    @pytest.mark.asyncio
    async def test_middleware_denies_and_hides_disallowed_tools(self, tmp_path):
        _write_skill(
            tmp_path / "skills",
            "n",
            "name: N\ndescription: n\nallowed_tools:\n  - read_file",
        )
        mw = SkillsMiddleware(search_dirs=[str(tmp_path / "skills")])
        mw.manager.load("N")
        _, tools = await mw.on_before_send(
            [],
            [{"name": "read_file"}, {"name": "write_file"}],
        )
        assert [item["name"] for item in tools] == ["read_file"]
        allowed, _reason = await mw.on_before_tool("read_file", {})
        assert allowed is True
        denied, reason = await mw.on_before_tool("write_file", {})
        assert denied is False
        assert "write_file" in reason
        assert "allowed_tools" in reason

    @pytest.mark.asyncio
    async def test_agent_loop_enforces_allowed_tools_after_load(self, tmp_path):
        root = tmp_path / "skills"
        _write_skill(
            root,
            "narrow",
            "name: Narrow\ndescription: Read only\nallowed_tools:\n  - read_file\n  - load_skill",
            "Only read files.",
        )
        writes: list[str] = []

        async def write_file(file_path: str, content: str) -> str:
            writes.append(file_path)
            return "wrote"

        async def read_file(file_path: str) -> str:
            return "contents"

        tools = {
            "write_file": {
                "function": write_file,
                "schema": {
                    "name": "write_file",
                    "description": "Write",
                    "input_schema": {"type": "object", "properties": {}},
                },
            },
            "read_file": {
                "function": read_file,
                "schema": {
                    "name": "read_file",
                    "description": "Read",
                    "input_schema": {"type": "object", "properties": {}},
                },
            },
        }
        denied_events: list[ToolDenied] = []
        bus = EventBus()

        async def on_denied(event: ToolDenied) -> None:
            denied_events.append(event)

        bus.on(ToolDenied, on_denied)
        provider = ScriptedProvider(
            [
                ScriptedTurn.tools(
                    ToolUseBlock(id="1", name="load_skill", input={"name": "Narrow"})
                ),
                ScriptedTurn.tools(
                    ToolUseBlock(
                        id="2",
                        name="write_file",
                        input={"file_path": "secret.txt", "content": "nope"},
                    )
                ),
                ScriptedTurn.reply("stopped"),
            ]
        )
        agent = Agent(
            provider=provider,
            event_bus=bus,
            tools=tools,
            config=AgentConfig(skip_approval=True, provider_retry_base_delay=0.0),
            middleware_manager=MiddlewareManager(
                [SkillsMiddleware(search_dirs=[str(root)])]
            ),
        )
        await agent.initialize()
        assert await agent.run("use the skill") == "stopped"
        assert writes == []
        first_tools = [schema.get("name") for schema in provider.calls[0][1]]
        second_tools = [schema.get("name") for schema in provider.calls[1][1]]
        assert "write_file" in first_tools
        assert "write_file" not in second_tools
        assert "read_file" in second_tools
        assert any("outside loaded skill allowed_tools" in str(event.reason) for event in denied_events)
        assert "Only read files." in provider.calls[1][2]
