# 🔍 Improvement Analysis — OCC vs. Claude Code

This document compares **Open Claude Code (OCC)** with Anthropic's **Claude Code** CLI agent and identifies actionable improvements to close the gap.

---

## Feature Comparison

| Feature | Claude Code | OCC (Current) | Priority |
|---------|:-:|:-:|:-:|
| Multi-model support | ❌ (Claude only) | ✅ | — |
| Open source | ❌ | ✅ | — |
| 3 interaction modes | ✅ | ✅ | — |
| Tool use + agent loop | ✅ | ✅ | — |
| MCP integration | ✅ | ✅ | — |
| Skills (prompt extensions) | ✅ | ✅ | — |
| Streaming responses | ✅ | ❌ | 🔴 High |
| Git workflow automation | ✅ | ❌ | 🔴 High |
| File snapshots / undo | ✅ | ❌ | 🔴 High |
| Diff-based editing | ✅ | ❌ | 🔴 High |
| Persistent memory (cross-session) | ✅ | ❌ | 🟡 Medium |
| Hooks (pre/post command) | ✅ | ❌ | 🟡 Medium |
| Agent teams (multi-agent) | ✅ | ⚠️ Partial (`spawn_agent`) | 🟡 Medium |
| Cost / token tracking | ✅ | ❌ | 🟡 Medium |
| IDE integration (VS Code) | ✅ | ❌ | 🟢 Low |
| Session management | ✅ | ❌ | 🟢 Low |
| /loop recurring tasks | ✅ | ❌ | 🟢 Low |

---

## 🔴 High Priority Improvements

### 1. Streaming Responses

**What Claude Code does:** Tokens appear character-by-character as the model generates them, giving immediate feedback.

**Current OCC behavior:** Waits for the entire response before displaying anything, which feels sluggish on long responses.

**Suggested implementation:**
- Modify `providers/base.py` to add a `stream()` method returning an `AsyncIterator[ContentBlock]`
- Implement streaming in each provider (`anthropic.py`, `openai.py`, `gemini.py`)
- Update `agent.py` to emit `TokenDelta` events for real-time UI rendering
- Update `listeners/ui.py` to render streamed tokens using `rich.live`

---

### 2. Git Workflow Automation

**What Claude Code does:** Automatically stages, commits, creates branches, and even opens PRs — treating Git as a first-class tool.

**Current OCC behavior:** Users must manually run Git commands via `run_shell`.

**Suggested implementation:**
- Add a `git_tools.py` module with tools: `git_commit`, `git_branch`, `git_diff`, `git_status`, `git_stash`
- Add a `git_pr` tool that creates GitHub PRs via the API
- Auto-stage edited files after `write_file` and `edit_file` calls (configurable)
- Add a `/git` slash command for quick Git operations

---

### 3. File Snapshots & Undo

**What Claude Code does:** Snapshots files before editing, allowing one-command rollback.

**Current OCC behavior:** No backup mechanism — edits are immediately destructive and irreversible.

**Suggested implementation:**
- Before any `edit_file` or `write_file` operation, copy the original to `.occ/snapshots/<hash>`
- Add an `undo_edit` tool that reverts the last edit to a file
- Add `/undo` slash command that reverts the last N file changes
- Store snapshot metadata (timestamp, tool call ID, file path) in a SQLite database

---

### 4. Diff-Based Editing

**What Claude Code does:** Uses line-based search-and-replace with unified diff format for precise multi-region edits.

**Current OCC behavior:** `edit_file` does single-string replacement, requiring exact-match uniqueness — fails on repeated patterns.

**Suggested implementation:**
- Add a `multi_edit` tool that accepts a list of `{old_string, new_string}` pairs
- Add a `patch_file` tool that accepts unified diff format
- Show colorized diffs (red/green) in the terminal after each edit
- Consider using `difflib` for fuzzy matching to handle minor whitespace differences

---

## 🟡 Medium Priority Improvements

### 5. Persistent Memory (Cross-Session)

**What Claude Code does:** Learns project-specific conventions, build commands, and debugging insights. Remembers them across sessions.

**Current OCC behavior:** Memory middleware loads `AGENTS.md`/`CLAUDE.md` files (static), but nothing is *learned* or persisted from conversations.

**Suggested implementation:**
- At end of each session, use LLM to extract key learnings (conventions, preferences, gotchas)
- Store in `.occ/memory/learnings.yml` — key-value pairs the agent references in future sessions
- Add a `/remember <note>` command for explicit memory storage
- Add a `/forget` command to clear learned preferences

---

### 6. Hooks System (Pre/Post Actions)

**What Claude Code does:** Users can configure shell hooks that run automatically before/after tool executions (e.g., auto-lint after file edits, auto-format on save).

**Current OCC behavior:** The plugin system has lifecycle hooks but no simple "run this shell command after edit" mechanism.

**Suggested implementation:**
- Add a `hooks` section to `occ.yml`:
  ```yaml
  hooks:
    post_edit:
      - "ruff check --fix {file_path}"
      - "black {file_path}"
    post_write:
      - "prettier --write {file_path}"
  ```
- Execute hooks automatically after the corresponding tool completes
- Report hook results in the tool output

---

### 7. Enhanced Multi-Agent Coordination

**What Claude Code does:** Agent teams with a lead agent that delegates tasks to worker agents, tracks their progress, and synthesizes results.

**Current OCC behavior:** `spawn_agent` runs sub-agents concurrently but without coordination — no progress tracking, no result synthesis, no delegation strategy.

**Suggested implementation:**
- Add an `AgentOrchestrator` that manages a pool of sub-agents
- Lead agent creates a task graph, delegates sub-tasks, and monitors progress
- Sub-agents share a read-only view of the conversation context
- Results are automatically synthesized into a coherent response

---

### 8. Cost & Token Tracking

**What Claude Code does:** Shows real-time token usage and estimated cost per session.

**Current OCC behavior:** Estimates tokens internally for compaction but doesn't expose this to the user.

**Suggested implementation:**
- Track `input_tokens`, `output_tokens`, and `cached_tokens` from each API response
- Maintain a running total per session in a `CostTracker` dataclass
- Display a summary on `/cost` slash command
- Show a subtle token counter in the REPL prompt (e.g., `❯ [2.1k tokens]`)

---

## 🟢 Low Priority Improvements

### 9. IDE Integration

Add a VS Code extension that wraps OCC as a sidebar chat, similar to GitHub Copilot Chat.

### 10. Session Management

Support saving/loading/naming sessions:
```
/session save refactor-auth
/session load refactor-auth
/session list
```

### 11. /loop — Recurring Tasks

Support scheduled, recurring tasks:
```
/loop every 30m "run tests and report failures"
```

---

## Quick Wins (Easy to Implement)

| Improvement | Effort | Impact |
|------------|--------|--------|
| Show colorized diffs after `edit_file` | 🟢 Small | High — much better UX |
| Add `--version` flag to CLI | 🟢 Small | Expected for any CLI tool |
| Add `--quiet` / `--verbose` flags | 🟢 Small | Better scripting support |
| Add a `git_diff` tool | 🟢 Small | Very useful for code review |
| Show token count in prompt | 🟢 Small | Cost awareness |
| Export conversation to Markdown | 🟡 Medium | Useful for documentation |
| Add tab-completion for slash commands | 🟡 Medium | Better DX |
| Add `--non-interactive` mode for piping | 🟡 Medium | CI/CD integration |

---

## Summary

OCC's biggest advantage is its **multi-model, open-source** nature. Claude Code locks you into Claude; OCC works with any LLM.

The highest-impact improvements to prioritize:
1. **Streaming responses** — makes the agent feel 10x more responsive
2. **Git integration** — removes the biggest friction point for daily use
3. **File snapshots** — safety net that makes users trust the agent more
4. **Diff-based editing** — handles complex multi-region edits that `edit_file` can't

These four changes would bring OCC to feature parity with Claude Code on the features that matter most to daily users.
