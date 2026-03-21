"""Tests for the planning system — PlanStore, tools, and middleware."""

import asyncio

import pytest

from open_claude_code.planning.store import PlanItem, PlanStore
from open_claude_code.planning.tools import make_plan_tools
from open_claude_code.planning.middleware import PlanningMiddleware


# ── PlanStore tests ────────────────────────────────────────────────

class TestPlanStore:
    """Tests for PlanStore CRUD operations."""

    def test_initial_state(self):
        """New store has no active plan."""
        store = PlanStore()
        assert not store.is_active
        assert store.progress == (0, 0)
        assert store.progress_str == "No plan"

    def test_write_creates_plan(self):
        """write() creates a plan with items."""
        store = PlanStore()
        result = store.write("My Plan", ["Step A", "Step B", "Step C"])

        assert store.is_active
        assert store.title == "My Plan"
        assert len(store.items) == 3
        assert store.items[0].id == "step_1"
        assert store.items[0].text == "Step A"
        assert store.items[0].status == "pending"
        assert "My Plan" in result
        assert "3 steps" in result

    def test_write_overwrites(self):
        """write() replaces existing plan."""
        store = PlanStore()
        store.write("Plan 1", ["A", "B"])
        store.write("Plan 2", ["X", "Y", "Z"])

        assert store.title == "Plan 2"
        assert len(store.items) == 3

    def test_write_skips_empty(self):
        """write() skips empty step strings."""
        store = PlanStore()
        store.write("Test", ["A", "", "  ", "B"])
        assert len(store.items) == 2

    def test_update_status(self):
        """update() changes item status."""
        store = PlanStore()
        store.write("Test", ["Step 1", "Step 2"])

        result = store.update("step_1", status="in_progress")
        assert store.items[0].status == "in_progress"
        assert "in_progress" in result

        result = store.update("step_1", status="done")
        assert store.items[0].status == "done"

    def test_update_text(self):
        """update() changes item text."""
        store = PlanStore()
        store.write("Test", ["Original"])

        store.update("step_1", text="Updated text")
        assert store.items[0].text == "Updated text"

    def test_update_nonexistent(self):
        """update() returns error for unknown item."""
        store = PlanStore()
        store.write("Test", ["Step 1"])

        result = store.update("step_999", status="done")
        assert "Error" in result

    def test_add_appends(self):
        """add() appends an item by default."""
        store = PlanStore()
        store.write("Test", ["Step 1"])

        store.add("Step 2")
        assert len(store.items) == 2
        assert store.items[1].text == "Step 2"

    def test_add_after_id(self):
        """add() inserts after specified item."""
        store = PlanStore()
        store.write("Test", ["Step 1", "Step 3"])

        store.add("Step 2", after_id="step_1")
        assert len(store.items) == 3
        assert store.items[1].text == "Step 2"

    def test_add_after_nonexistent(self):
        """add() returns error for unknown after_id."""
        store = PlanStore()
        store.write("Test", ["Step 1"])

        result = store.add("Step 2", after_id="nope")
        assert "Error" in result

    def test_remove(self):
        """remove() deletes an item."""
        store = PlanStore()
        store.write("Test", ["Step 1", "Step 2", "Step 3"])

        store.remove("step_2")
        assert len(store.items) == 2
        assert all(i.id != "step_2" for i in store.items)

    def test_remove_nonexistent(self):
        """remove() returns error for unknown item."""
        store = PlanStore()
        store.write("Test", ["Step 1"])

        result = store.remove("nope")
        assert "Error" in result

    def test_progress(self):
        """progress tracks done vs total."""
        store = PlanStore()
        store.write("Test", ["A", "B", "C", "D"])

        assert store.progress == (0, 4)

        store.update("step_1", status="done")
        store.update("step_2", status="done")
        assert store.progress == (2, 4)
        assert "2/4" in store.progress_str

    def test_to_markdown(self):
        """to_markdown() returns formatted checklist."""
        store = PlanStore()
        store.write("Build Feature", ["Design", "Implement", "Test"])
        store.update("step_1", status="done")
        store.update("step_2", status="in_progress")

        md = store.to_markdown()
        assert "Build Feature" in md
        assert "[x]" in md  # done
        assert "[/]" in md  # in_progress
        assert "[ ]" in md  # pending
        assert "in progress" in md

    def test_to_compact(self):
        """to_compact() returns single-line summary."""
        store = PlanStore()
        assert store.to_compact() == ""

        store.write("Test", ["A", "B", "C"])
        assert "[Plan: 0/3]" in store.to_compact()

        store.update("step_1", status="in_progress")
        compact = store.to_compact()
        assert "0/3" in compact
        assert "Now:" in compact

    def test_plan_item_icons(self):
        """PlanItem icons are correct for each status."""
        assert PlanItem(id="1", text="", status="pending").icon == "○"
        assert PlanItem(id="1", text="", status="in_progress").icon == "◐"
        assert PlanItem(id="1", text="", status="done").icon == "●"

    def test_plan_item_checkboxes(self):
        """PlanItem checkboxes are correct."""
        assert PlanItem(id="1", text="", status="pending").checkbox == "[ ]"
        assert PlanItem(id="1", text="", status="in_progress").checkbox == "[/]"
        assert PlanItem(id="1", text="", status="done").checkbox == "[x]"


# ── Planning Tools tests ──────────────────────────────────────────

class TestPlanTools:
    """Tests for the planning tool functions."""

    def _make_tools(self):
        store = PlanStore()
        tools = make_plan_tools(store)
        return store, tools

    @pytest.mark.asyncio
    async def test_write_plan_tool(self):
        """write_plan creates a plan."""
        store, tools = self._make_tools()
        fn = tools["write_plan"]["function"]

        result = await fn(title="My Task", steps=["Do A", "Do B"])
        assert store.is_active
        assert len(store.items) == 2
        assert "My Task" in result

    @pytest.mark.asyncio
    async def test_update_plan_tool_status(self):
        """update_plan changes status."""
        store, tools = self._make_tools()
        write_fn = tools["write_plan"]["function"]
        update_fn = tools["update_plan"]["function"]

        await write_fn(title="Test", steps=["Step"])
        result = await update_fn(action="update", item_id="step_1", status="done")
        assert store.items[0].status == "done"

    @pytest.mark.asyncio
    async def test_update_plan_tool_add(self):
        """update_plan can add items."""
        store, tools = self._make_tools()
        write_fn = tools["write_plan"]["function"]
        update_fn = tools["update_plan"]["function"]

        await write_fn(title="Test", steps=["Step 1"])
        result = await update_fn(action="add", text="Step 2")
        assert len(store.items) == 2

    @pytest.mark.asyncio
    async def test_update_plan_tool_remove(self):
        """update_plan can remove items."""
        store, tools = self._make_tools()
        write_fn = tools["write_plan"]["function"]
        update_fn = tools["update_plan"]["function"]

        await write_fn(title="Test", steps=["A", "B"])
        result = await update_fn(action="remove", item_id="step_1")
        assert len(store.items) == 1

    @pytest.mark.asyncio
    async def test_read_plan_tool(self):
        """read_plan returns markdown."""
        store, tools = self._make_tools()
        write_fn = tools["write_plan"]["function"]
        read_fn = tools["read_plan"]["function"]

        await write_fn(title="Test Plan", steps=["Alpha"])
        result = await read_fn()
        assert "Test Plan" in result
        assert "Alpha" in result

    @pytest.mark.asyncio
    async def test_read_plan_empty(self):
        """read_plan returns placeholder when no plan exists."""
        _, tools = self._make_tools()
        read_fn = tools["read_plan"]["function"]

        result = await read_fn()
        assert "No active plan" in result

    @pytest.mark.asyncio
    async def test_update_plan_tool_errors(self):
        """update_plan returns errors for invalid operations."""
        store, tools = self._make_tools()
        update_fn = tools["update_plan"]["function"]

        # Missing item_id for update
        result = await update_fn(action="update")
        assert "Error" in result

        # Missing text for add
        result = await update_fn(action="add")
        assert "Error" in result

        # Unknown action
        result = await update_fn(action="invalid")
        assert "Error" in result

    def test_tool_schemas_valid(self):
        """Tool schemas have required fields."""
        _, tools = self._make_tools()

        for name in ("write_plan", "update_plan", "read_plan"):
            schema = tools[name]["schema"]
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema
            assert schema["name"] == name


# ── PlanningMiddleware tests ──────────────────────────────────────

class TestPlanningMiddleware:
    """Tests for PlanningMiddleware."""

    def test_name(self):
        mw = PlanningMiddleware()
        assert mw.name == "planning"

    def test_get_tools_returns_three(self):
        """Middleware provides 3 planning tools."""
        mw = PlanningMiddleware()
        tools = mw.get_tools()
        assert "write_plan" in tools
        assert "update_plan" in tools
        assert "read_plan" in tools

    def test_prompt_no_plan(self):
        """Prompt addition encourages plan usage when no plan exists."""
        mw = PlanningMiddleware()
        prompt = mw.get_prompt_additions()
        assert "Planning" in prompt
        assert "write_plan" in prompt

    def test_prompt_with_plan(self):
        """Prompt includes plan state when plan is active."""
        mw = PlanningMiddleware()
        mw.store.write("Test Plan", ["Step 1", "Step 2"])

        prompt = mw.get_prompt_additions()
        assert "Current Plan" in prompt
        assert "Test Plan" in prompt
        assert "Step 1" in prompt

    def test_slash_command_show(self):
        """Handles /plan show command."""
        mw = PlanningMiddleware()
        result = mw.handle_slash_command("/plan", "show")
        assert result == "handled"

    def test_slash_command_clear(self):
        """Handles /plan clear command."""
        mw = PlanningMiddleware()
        mw.store.write("Test", ["A"])
        assert mw.store.is_active

        result = mw.handle_slash_command("/plan", "clear")
        assert result == "handled"
        assert not mw.store.is_active

    def test_slash_command_unhandled(self):
        """Ignores non-plan slash commands."""
        mw = PlanningMiddleware()
        result = mw.handle_slash_command("/mode", "agent")
        assert result is None
