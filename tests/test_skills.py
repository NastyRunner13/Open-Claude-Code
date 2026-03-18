"""Tests for the skills system."""

from pathlib import Path

from open_claude_code.skills.loader import Skill, SkillManager, parse_skill_md


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
