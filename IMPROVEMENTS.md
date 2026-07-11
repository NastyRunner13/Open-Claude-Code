# OCC Improvement Roadmap

This document reviews Open Claude Code (OCC) against current Codex and Claude
Code capabilities, then maps those product ideas onto this codebase. It is
intentionally implementation-oriented: each recommendation names the current
gap, why it matters, and where to start.

Research checked during this review:

- OpenAI Codex CLI features: https://developers.openai.com/codex/cli/features
- OpenAI Codex subagents: https://developers.openai.com/codex/subagents
- OpenAI Codex non-interactive mode: https://developers.openai.com/codex/noninteractive
- OpenAI Codex MCP: https://developers.openai.com/codex/mcp
- OpenAI Codex app automations: https://developers.openai.com/codex/app/automations
- Claude Code extension overview: https://code.claude.com/docs/en/features-overview
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code hooks: https://code.claude.com/docs/en/hooks
- Claude Code scheduled tasks: https://code.claude.com/docs/en/scheduled-tasks
- Claude Code programmatic mode: https://code.claude.com/docs/en/headless
- Claude Code GitHub Actions: https://code.claude.com/docs/en/github-actions

## Executive Summary

OCC already has a good skeleton: provider abstraction, event bus, middleware,
planning tools, skills, memory-file loading, MCP scaffolding, subagent spawning,
and a test suite. The biggest opportunity is not adding more providers; it is
making the agent trustworthy, observable, resumable, automatable, and safe under
real coding workloads.

Highest priority:

1. Fix correctness gaps first: MCP tool invocation is currently broken, plugins
   are documented but not wired into the CLI, plan mode can still call
   destructive tools, and context compaction ignores the `context_compaction`
   config flag.
2. Add a safety layer before expanding autonomy: path sandboxing, command
   policy, file snapshots, diffs, undo, and structured approvals.
3. Add streaming and persistent sessions: these change the perceived quality of
   the product more than most features.
4. Build automation as a first-class runtime: non-interactive mode, JSONL event
   streams, scheduled tasks, hooks, GitHub Actions, and durable task state.
5. Improve agent intelligence with code intelligence, better subagent
   orchestration, skill loading on demand, and evaluation traces.

## Current OCC Feature Inventory

Implemented or partially implemented:

- Multi-provider model support: Anthropic, OpenAI-compatible, Gemini, Groq,
  Ollama.
- Three modes: ask, plan, agent.
- Built-in tools: file read/write/edit, directory listing, grep, glob, shell,
  web search, URL read, Python sandbox, skill loading, subagent spawn.
- Event bus for Thinking, PreToolUse, PostToolUse, Stop, SubagentStart, and
  SubagentStop.
- Middleware architecture for memory, planning, skills, and MCP.
- Project memory files: `AGENTS.md`, `CLAUDE.md`, `.occ/memory.md`, etc.
- In-memory plan checklist tools.
- Basic exact-match edit tool.
- Basic MCP stdio client.
- Basic plugin loader.
- LLM-based context compaction.
- Non-bypassable agent-level tool policy with configurable modes and deny rules.
- Durable local session metadata and JSONL ledger, including CLI resume and
  session listing.
- Rich/prompt-toolkit terminal UI.
- Tests for core agent loop, providers, tools, config, planning, memory,
  skills, middleware, events, and context.

Not yet implemented or not wired end-to-end:

- Streaming tokens and streaming tool/progress events.
- Rich transcripts with file-change snapshots, usage, provider deltas, and
  exportable task capsules.
- File snapshots, rollback, diff review, multi-edit, unified patch application.
- Network egress policy and fine-grained per-MCP/per-plugin capability policy.
- Cost/token accounting surfaced to the user.
- Non-interactive CLI mode for scripts and CI.
- JSONL event output for automation.
- Scheduled tasks, reminders, monitors, and recurring loops.
- Git and GitHub first-class workflows.
- IDE extension, language-server code intelligence, diagnostics.
- Remote/browser/desktop control surfaces.
- Plugin execution in the main CLI runtime.
- Full MCP support: HTTP transport, OAuth, server instructions, resources,
  prompts, elicitation, and per-tool policy.

## Important Codebase Issues To Fix

These are not just wishlist items; they are current product correctness or
trust issues.

### 1. MCP Tools Are Registered With No Callable Function

File: `src/open_claude_code/mcp/client.py`

`MCPManager.get_occ_tools()` creates OCC tool schemas, but the `"function"`
field is left as `None`. The nested `make_caller()` closure is never awaited or
assigned. If the model calls an MCP tool, `Agent.run()` will try `await
tool_fn(**block.input)` and fail with a `NoneType` call error.

Fix:

- Replace the unused closure with a real bound async function per tool.
- Add a regression test that injects a fake MCP client/tool and calls the OCC
  wrapper.
- Return `ToolResult` instead of plain strings for consistent metadata.

Suggested patch shape:

```python
def make_caller(tool_name: str):
    async def caller(**kwargs: Any) -> str:
        return await self.call_tool(tool_name, kwargs)
    return caller

occ_tools[occ_name] = {
    "function": make_caller(tool.name),
    "schema": ...
}
```

### 2. Plugin System Is Documented But Not Wired Into The CLI

Files:

- `src/open_claude_code/plugins/manager.py`
- `src/open_claude_code/main.py`
- `src/open_claude_code/config.py`
- `README.md`

`AgentConfig.plugins_dirs` exists and the README advertises Python plugins, but
`main.py` never creates `PluginManager`, scans plugin directories, or emits
plugin hooks from the agent loop. That means plugins are currently a tested
library component, not a user-visible feature.

Fix:

- Add `PluginMiddleware` that wraps `PluginManager`.
- Call plugin hooks from the event/middleware lifecycle:
  `on_agent_start`, `on_before_send`, `on_after_response`, `on_tool_result`,
  `on_agent_stop`.
- Add `/plugin list`, `/plugin reload`, `/plugin enable`, `/plugin disable`.
- Decide whether plugins can add tools. If yes, standardize the schema shape.
- Update docs after wiring the feature.

### 3. Plan Mode Is Prompt-Only Safe, Not Runtime-Enforced Safe

Files:

- `src/open_claude_code/modes.py`
- `src/open_claude_code/agent.py`

Plan mode asks the model not to modify files, but it keeps the normal tool
registry active during planning. A model can still request `write_file`,
`edit_file`, `run_shell`, or `sandbox`; the only barrier is the approval prompt.
That is weaker than the product promise of "plan then execute".

Fix:

- During plan generation, restrict tools to read-only exploration:
  `read_file`, `list_directory`, `find_files`, `grep_search`, `web_search`,
  `read_url`, `read_plan`, maybe `write_plan`.
- Enforce this in code, not just in the prompt.
- Add a `ToolPolicy` layer that can deny tool calls before approval handling.

### 4. `context_compaction` Config Is Ignored

Files:

- `src/open_claude_code/config.py`
- `src/open_claude_code/agent.py`

`AgentConfig.context_compaction` is parsed, but `Agent.run()` always calls
`auto_compact_async()`. Users cannot actually disable compaction.

Fix:

- Gate auto-compaction with `if not config or config.context_compaction:`.
- Add a test that sets `context_compaction=False`.

### 5. `max_tool_output` Config Is Ignored

Files:

- `src/open_claude_code/config.py`
- `src/open_claude_code/tools/*.py`

The config includes `max_tool_output`, but tools use module-level constants such
as `MAX_OUTPUT = 10000`. This prevents users from tuning output size globally or
per tool.

Fix:

- Introduce a `ToolContext` object passed to every tool.
- Include config, cwd, sandbox policy, output limits, and session ID in that
  context.
- Keep legacy standalone tool functions for tests if needed, but route CLI
  runtime through context-bound tool wrappers.

### 6. File Tools Need A Workspace Sandbox

Files:

- `src/open_claude_code/tools/read_file.py`
- `src/open_claude_code/tools/write_file.py`
- `src/open_claude_code/tools/edit_file.py`
- `src/open_claude_code/tools/list_directory.py`
- `src/open_claude_code/tools/find_files.py`
- `src/open_claude_code/tools/grep_search.py`

Auto-approved read tools can read arbitrary paths if the model supplies them.
Approved write/edit tools can write arbitrary paths. This is risky once you add
automation, scheduled tasks, or broad auto-approval modes.

Fix:

- Add `workspace_roots` and `writable_roots` to config.
- Resolve every path with `Path.resolve()`.
- Deny reads outside allowed roots unless explicitly approved.
- Deny writes outside writable roots unless a high-trust permission mode is
  active.
- Log every denied path access as an event.

### 7. Shell Tool Needs Structured Policy And Better Runtime Control

File: `src/open_claude_code/tools/run_shell.py`

Current shell execution is an all-or-nothing approved command string. It has no
command classifier, no network/write policy, no cwd override, no env control, no
PTY support, no streaming output, no process-tree cleanup, and no structured
command segments.

Fix:

- Add command metadata: cwd, env allowlist, timeout, shell, requires_network,
  writes_paths, destructive flag.
- Add policy presets: `read-only`, `workspace-write`, `full-access`.
- Split command approval from command execution.
- Stream stdout/stderr as events.
- Kill process groups on timeout.
- Persist command output artifacts for long logs instead of dumping everything
  into context.

### 8. `read_url` And `web_search` Need Web Safety Controls

Files:

- `src/open_claude_code/tools/read_url.py`
- `src/open_claude_code/tools/web_search.py`

`read_url` can fetch arbitrary URLs and returns raw page text into the model
context. It has no URL scheme validation, private-network blocking, content
length limit before download, robots/policy controls, or prompt-injection
labeling. `web_search` is auto-approved and depends on a third-party package.

Fix:

- Allow only `http` and `https`.
- Block localhost, link-local, RFC1918, metadata IPs, and file/data schemes by
  default.
- Add configurable domain allow/deny lists.
- Add source metadata and explicit "untrusted web content" wrapping.
- Prefer official docs domains when the task asks about known vendor products.
- Cache search/read results in `.occ/cache/web/`.

### 9. Provider Abstraction Lacks Streaming, Usage, Retries, And Structured Errors

Files:

- `src/open_claude_code/providers/base.py`
- `src/open_claude_code/providers/*.py`
- `src/open_claude_code/agent.py`

`ProviderResponse` only contains `thinking` and `content`. There is no usage,
cost, latency, request ID, finish reason, safety status, or retry metadata. The
agent cannot stream tokens or tool-call deltas. Provider errors are plain
strings.

Fix:

- Add `ProviderUsage`, `ProviderMetadata`, and typed `ProviderError` subclasses.
- Add `stream()` to the provider protocol.
- Emit `TokenDelta`, `ToolCallDelta`, `UsageUpdated`, and `ProviderError`
  events.
- Add retry/backoff for transient API failures.
- Track request IDs for support/debugging.

### 10. OpenAI Provider Should Move Toward The Responses API

File: `src/open_claude_code/providers/openai.py`

The OpenAI provider uses Chat Completions. For a coding-agent product, the
Responses API is the better long-term abstraction because it aligns with modern
tool use, reasoning, streaming events, structured outputs, and future OpenAI
agent capabilities.

Fix:

- Add a Responses-based provider implementation.
- Keep Chat Completions as a compatibility provider for OpenAI-compatible
  endpoints.
- Support reasoning effort, structured outputs, streamed response events, and
  usage metadata.

### 11. Subagents Are Useful But Too Coarse

Files:

- `src/open_claude_code/tools/spawn_agent.py`
- `src/open_claude_code/subagents/manager.py`

Current subagents share the parent provider, get the parent tools minus
`spawn_agent`, and default to an enforced read-only capability policy. They do
not yet get middleware prompt additions, custom roles/models, worktree
isolation, or independent transcripts, which limits them to safe research
tasks rather than implementation work.

Fix:

- Add custom subagent definitions under `.occ/agents/*.md`.
- Support per-agent model, system prompt, tools, disallowed tools, max turns,
  memory scope, and permission policy.
- Add agent IDs, transcripts, resumable threads, and `/agent` management.
- Default subagents to read-only unless explicitly elevated.
- Summarize verbose subagent output before returning to parent context.

### 12. Skills Load Too Much Context

Files:

- `src/open_claude_code/skills/loader.py`
- `src/open_claude_code/middleware/skills.py`

Loaded skills inject full instructions into every request. Claude Code and
Codex-style skills usually load lightweight metadata first, then load full skill
content on invocation or when the model chooses it.

Fix:

- Separate skill metadata from full skill content.
- Add `disable_model_invocation`, `allowed_tools`, `scripts`, and `assets`
  frontmatter.
- Let the model see only names/descriptions initially.
- Load full content through the `load_skill` tool or direct slash command.
- Add namespaced plugin skills.

### 13. Session History Has A Durable Baseline, Not A Full Task Capsule

Files:

- `src/open_claude_code/agent.py`
- `src/open_claude_code/main.py`

OCC now stores redacted session metadata and an append-only JSONL history/tool
ledger under `.occ/sessions`, supports `occ --resume <session-id>`, and lists
sessions with `/sessions`. This is enough for local conversation resumption and
basic auditability.

Remaining work:

- Record provider deltas, file changes, approvals, errors, usage, and plan
  updates as structured events.
- Give each subagent its own nested transcript.
- Add `/rename`, `/export`, reproducible task capsules, and `--ephemeral`.

## Feature Parity Matrix

| Capability | Codex / Claude Code baseline | OCC today | Priority |
| --- | --- | --- | --- |
| Streaming responses | Supported | No | P0 |
| Diffs and syntax highlighting | Supported | No diff review | P0 |
| File snapshots / undo | Rollback via transcript/git workflow patterns | No | P0 |
| Runtime permission modes | Sandbox/approval modes | Basic capability modes + path/shell policy | P0 |
| Durable sessions / resume | Supported | Local JSONL + CLI resume | P1 |
| MCP | Richer transports/auth/instructions | Basic stdio tools; richer transports pending | P0 |
| Plugins | Packaging layer | Runtime hooks wired; packaging/sandboxing pending | P1 |
| Non-interactive mode | `codex exec`, `claude -p` | No | P1 |
| JSONL event stream | Supported by Codex exec | No | P1 |
| Scheduled tasks / loops | Claude `/loop`, scheduled tasks | No | P1 |
| Hooks | Claude hooks, Codex hooks/config | No runtime hooks | P1 |
| GitHub automation | GitHub Actions / PR workflows | No first-class support | P1 |
| Subagent orchestration | Custom agents, isolated contexts | Basic spawn only | P1 |
| Cost / token tracking | Exposed in automation outputs | No | P1 |
| Code review workflow | `/review` and GitHub review | No | P1 |
| Code intelligence | Claude language-server feature | No | P2 |
| IDE integration | Codex/Claude extensions | No | P2 |
| Image inputs | Codex supports images | No | P2 |
| Image generation/assets | Codex supports image generation | No | P3 |
| Remote/web/mobile control | Codex app server, Claude remote control | No | P3 |

## Features Worth Copying From Codex

### Interactive TUI Quality

Codex emphasizes real-time review: streamed progress, syntax-highlighted code,
diffs, queued follow-ups, prompt history search, copy-last-output, and
permission changes during a session.

OCC implementation ideas:

- Add streaming provider events.
- Show live tool status and command output.
- Render diffs after every file write/edit.
- Add prompt history search and slash-command completion.
- Add `/permissions`, `/status`, `/copy`, `/theme`, `/exit`.

### Resumable Sessions

Codex stores transcripts locally and supports resuming previous sessions,
including non-interactive runs.

OCC implementation ideas:

- Persist JSONL transcripts under `.occ/sessions`.
- Store session summary, cwd, model, mode, config hash, approval history, and
  plan state.
- Add `occ resume`, `occ resume --last`, `occ resume --all`, and `/resume`.

### Non-Interactive Automation

Codex `exec` is designed for scripts and CI, with final output on stdout,
progress on stderr, JSONL event mode, structured output schemas, and explicit
sandbox/approval settings.

OCC implementation ideas:

- Add `occ exec "<task>"`.
- Add `--json` for JSONL events.
- Add `--output-last-message <path>`.
- Add `--output-schema <schema.json>` for structured final responses.
- Add `--sandbox read-only|workspace-write|full-access`.
- Add `--approval-mode suggest|auto|full-access`.

### Cloud/Background Tasks

Codex supports launching cloud tasks and applying diffs locally. A fully managed
cloud system is probably later-stage for OCC, but the abstraction is worth
copying.

OCC implementation ideas:

- Start with local background tasks in `.occ/tasks`.
- Model tasks as durable state machines: queued, running, blocked, completed,
  failed, cancelled.
- Later add remote executors over SSH, containers, GitHub Actions, or a hosted
  worker.

### Local Code Review

Codex has a dedicated review workflow that inspects diffs and reports
prioritized findings without touching the working tree.

OCC implementation ideas:

- Add `/review`.
- Support review targets: uncommitted, staged, branch vs base, commit, file.
- Use a separate read-only reviewer agent.
- Output severity, file/line, evidence, and suggested fix.
- Add `occ review --json` for CI.

### MCP Maturity

Codex supports stdio and streamable HTTP MCP servers, bearer/OAuth auth, server
instructions, per-server/tool policy, and plugin-provided MCP servers.

OCC implementation ideas:

- Fix stdio tool invocation first.
- Add server instructions into prompt additions.
- Add HTTP transport.
- Add OAuth and bearer-token config.
- Add enabled/disabled tool filters.
- Add per-tool approval mode.
- Add resources, prompts, elicitation, and timeout controls.

## Features Worth Copying From Claude Code

### Extension Model: CLAUDE.md, Skills, Subagents, Hooks, MCP, Plugins

Claude Code's most important product lesson is feature separation:

- Memory files are always-on project conventions.
- Skills are on-demand workflows or reference material.
- MCP connects external systems.
- Subagents isolate large or specialized work.
- Hooks automate lifecycle events.
- Plugins package reusable combinations.

OCC already has pieces of this but needs sharper loading rules and a real plugin
runtime.

### Scheduled Tasks And `/loop`

Claude Code supports session-scoped scheduled prompts with `/loop`, one-time
reminders, cron-like scheduling, task management, expiry, and guidance for
durable unattended scheduling through routines, desktop scheduled tasks, or
GitHub Actions.

OCC implementation ideas:

- Add `/loop every 30m "check test status and report failures"`.
- Add `/remind at 17:00 "review PR #123"`.
- Add `/tasks list|pause|resume|cancel|show`.
- Store task state in `.occ/tasks.sqlite`.
- Use APScheduler or a small asyncio scheduler for in-session tasks.
- For unattended durable tasks, generate OS scheduler entries or GitHub Actions
  workflows rather than keeping a terminal process alive forever.

### Hooks

Claude Code hooks can be command, HTTP, MCP tool, prompt, or agent hooks on
events such as PreToolUse, PostToolUse, Stop, SubagentStop, SessionStart, and
FileChanged.

OCC implementation ideas:

- Add `hooks` to config:

```yaml
hooks:
  post_edit:
    - type: command
      command: "ruff check --fix {file_path}"
  pre_shell:
    - type: prompt
      prompt: "Allow this command? {json}"
  stop:
    - type: agent
      agent: verifier
      prompt: "Check whether all requested work is complete."
```

- Reuse the event bus as the dispatch layer.
- Feed hook denials back to the model as tool errors.
- Capture hook stdout/stderr in transcripts.

### Custom Subagents

Claude Code supports custom subagent files with metadata such as model,
permission mode, tools, MCP servers, hooks, skills, memory, max turns,
background behavior, and isolation.

OCC implementation ideas:

- Add `.occ/agents/code-reviewer.md`, `.occ/agents/test-runner.md`,
  `.occ/agents/security-auditor.md`.
- Create an `AgentRegistry`.
- Add `spawn_agent` parameters for `agent_name`, `task`, `model`, `policy`,
  `max_turns`, and `background`.
- Persist subagent transcripts separately.

### Persistent Agent Memory

Claude Code supports subagent memory scopes (`user`, `project`, `local`) and
encourages agents to curate memory over time.

OCC implementation ideas:

- Keep current memory-file loading.
- Add learned memory:
  - User: `~/.occ/memory/user.md`
  - Project: `.occ/memory/project.md`
  - Local: `.occ/memory/local.md`
  - Agent-specific: `.occ/agent-memory/<agent>/MEMORY.md`
- Add `/remember`, `/forget`, `/memory edit`, `/memory compact`.
- Use hooks to suggest memory updates at session end.

### Programmatic SDK

Claude Code exposes the same core agent loop through CLI, Python, and
TypeScript SDK paths.

OCC implementation ideas:

- Stabilize the Python API around `Agent`, `AgentConfig`, `ToolContext`, and
  event streams.
- Add `open_claude_code.sdk.run_task()`.
- Return structured `RunResult` with final text, events, usage, file changes,
  and transcript path.
- Later add TypeScript bindings or a local HTTP app server.

### GitHub Actions

Claude Code's GitHub Action turns PR/issue comments and workflow prompts into
implementation, review, and bug-fix automation.

OCC implementation ideas:

- Add `.github/actions/occ-action` or publish a reusable action.
- Support triggers:
  - `@occ` issue/PR comment
  - scheduled review
  - CI failure triage
  - release-note generation
- Use `occ exec --json` internally.
- Require least-privilege tokens.
- Produce PR comments with findings and optionally push a branch.

## Product Roadmap

### Phase 0: Stabilize The Existing Product

Goal: make the documented features true and safe.

- Fix MCP tool callable registration.
- Wire plugins into the runtime or remove plugin claims from docs until wired.
- Enforce read-only tool policy during plan generation.
- Respect `context_compaction`.
- Respect `max_tool_output`.
- Add path sandboxing for all filesystem tools.
- Add structured shell policy.
- Add tests for the above.
- Fix README and `IMPROVEMENTS.md` encoding/emoji portability if Windows
  terminals remain a target.

### Phase 1: Trust Layer

Goal: users should feel safe letting OCC edit code.

- Add file snapshots before every write/edit.
- Add `/undo` and `undo_edit` tool.
- Add colorized diffs after edits.
- Add `multi_edit` and `apply_patch` tools.
- Add edit transaction grouping: start, preview diff, commit, rollback.
- Add immutable file-change events in transcripts.
- Add policy modes:
  - `read-only`
  - `suggest`
  - `workspace-write`
  - `full-access`
- Add per-tool and per-path approval rules.

### Phase 2: Streaming And Sessions

Goal: make OCC feel fast and professional.

- Add provider streaming.
- Add token/progress events.
- Add command output streaming.
- Add local JSONL transcripts.
- Add `/status`, `/cost`, `/sessions`, `/resume`, `/export`.
- Add usage/cost accounting for all providers.
- Add retry/backoff and rate-limit messages.

### Phase 3: Automation Runtime

Goal: make OCC useful outside an interactive terminal.

- Add `occ exec`.
- Add `--json` event stream.
- Add structured output schema.
- Add `--output-last-message`.
- Add `--ephemeral`.
- Add scheduler:
  - `/loop`
  - `/remind`
  - `/tasks`
  - task SQLite store
- Add GitHub Action.
- Add hook runtime.
- Add notification hooks.

### Phase 4: Git And Review Workflows

Goal: make daily coding workflows first-class.

- Add tools:
  - `git_status`
  - `git_diff`
  - `git_log`
  - `git_branch`
  - `git_commit`
  - `git_stash`
  - `git_apply_patch`
- Add slash commands:
  - `/review`
  - `/commit`
  - `/pr`
  - `/branch`
  - `/changes`
- Add GitHub integration through CLI/API/MCP.
- Add PR description generation.
- Add CI failure triage.
- Add branch/worktree management for parallel attempts.

### Phase 5: Intelligence Layer

Goal: make OCC better at understanding large codebases.

- Add language-server code intelligence:
  - symbol search
  - go-to definition
  - references
  - diagnostics after edits
  - type errors
- Add repo map generation.
- Add semantic file ranking.
- Add dependency graph indexing.
- Add test selection.
- Add model routing:
  - fast model for classification/hooks
  - strong model for planning/implementation
  - local model for cheap summarization
- Add eval harness and golden task suite.

### Phase 6: Multi-Agent System

Goal: parallelize large work without losing control.

- Add custom agent definitions.
- Add subagent memory.
- Add agent transcripts and resume.
- Add background agents.
- Add coordinator that can fan out research/review tasks and synthesize.
- Add explicit "best-of-N implementation attempts" using worktrees.
- Add reviewer/verifier agents that run after changes.

### Phase 7: Interfaces And Ecosystem

Goal: make OCC available where developers already work.

- VS Code extension.
- JetBrains extension later.
- Local app server with WebSocket event stream.
- Browser-based UI for local sessions.
- MCP server mode so other agents can call OCC.
- Plugin marketplace format.
- Template repositories for skills, hooks, and agents.

## Suggested Architecture Changes

### Add `ToolContext`

Every tool should receive a context object:

```python
@dataclass
class ToolContext:
    cwd: Path
    config: AgentConfig
    session_id: str
    event_bus: EventBus
    policy: ToolPolicy
    max_output: int
```

Benefits:

- Centralizes sandbox and output limits.
- Lets tools emit events without importing UI code.
- Makes testing policy behavior easier.
- Supports per-session artifacts.

### Add `ToolPolicy`

Policy should decide whether a tool call is allowed, requires approval, or is
denied before execution.

Inputs:

- tool name
- tool params
- resolved filesystem paths
- command classification
- current permission mode
- current cwd and workspace roots
- session automation mode

Outputs:

- allow
- require approval with reason
- deny with reason

### Add `SessionStore`

Use JSONL for append-only transcripts and SQLite for indexed state.

Files:

- `.occ/sessions/<session_id>.jsonl`
- `.occ/state.sqlite`
- `.occ/tasks.sqlite`
- `.occ/snapshots/<session_id>/...`

Events to persist:

- thread/session started
- user message
- model started/completed
- token delta
- reasoning/thinking summary
- tool call started/completed/failed
- approval requested/approved/denied
- file snapshot created
- file changed
- plan changed
- usage updated
- task scheduled/fired/completed

### Add `ProviderStreamEvent`

Normalize provider streaming across Anthropic, OpenAI, Gemini, Groq, and Ollama:

- `message_start`
- `content_delta`
- `thinking_delta`
- `tool_call_delta`
- `tool_call_complete`
- `usage_delta`
- `message_complete`
- `error`

The agent loop should consume streams and produce the same final
`ProviderResponse` for history.

### Add `AutomationRunner`

This should run both interactive scheduled tasks and `occ exec`.

Responsibilities:

- load config
- create provider and agent
- select permission mode
- stream JSONL events
- write transcripts
- return final status code
- support cancellation

## Feature Ideas Beyond Parity

These would make OCC stand out rather than merely catch up.

### Provider Marketplace

Let users define provider profiles:

```yaml
providers:
  fast:
    type: openai
    model: gpt-5.3-codex-spark
  strong:
    type: anthropic
    model: claude-opus-4-8
  local:
    type: ollama
    model: qwen2.5-coder
```

Then use profiles for tasks: `planner_model`, `editor_model`,
`reviewer_model`, `summarizer_model`, `hook_model`.

### Agent Improvement Loop

After every task:

- Did tests pass?
- Did edits compile?
- Did reviewer find issues?
- How many turns and tool calls were needed?
- Which prompt or tool failed?

Store this as telemetry and use it to improve prompts, policies, and evals.

### Reproducible Task Capsules

For any agent run, export:

- prompt
- config
- model
- git commit
- diff
- tool event log
- final answer
- tests run

This makes bug reports and evals dramatically easier.

### Worktree-Based Parallel Attempts

For difficult changes:

- create N temporary git worktrees
- run separate agents with different strategies
- run tests in each
- compare diffs
- keep the best result
- clean up losers

This copies the "best-of-N cloud attempt" idea locally.

### Quality Gates

Before final response or commit:

- format changed files
- run targeted tests
- run type checker/linter
- run read-only reviewer
- verify no accidental secrets were added
- summarize changed files

Expose as `/verify`, `/ship`, and stop hooks.

## Quick Wins

Small changes with high impact:

- Fix MCP callable registration.
- Add `--version`.
- Add `/status` with model, mode, cwd, session ID, token estimate, config path.
- Add `git_diff` read-only tool.
- Show unified diff after `edit_file` and `write_file`.
- Add file snapshots for `edit_file` and `write_file`.
- Add `read_file` offset/limit and line numbers.
- Add `list_directory` ignore defaults for `.git`, `.venv`, `node_modules`,
  `dist`, `build`, and caches.
- Add command timeout display and exit status colorization.
- Add `--quiet` and `--verbose`.
- Add shell completions.
- Add slash command completion.
- Add `occ doctor` to validate API keys, provider availability, git repo, MCP
  servers, and common dependencies.

## Testing Improvements

Current tests cover many units, but the next phase needs integration and
behavior tests.

Add tests for:

- MCP wrapper invokes fake server tool successfully.
- Plan mode cannot execute write/edit/shell during planning.
- `context_compaction=False` prevents compaction.
- Tool output limit honors config.
- Path sandbox denies reads/writes outside workspace.
- Shell policy denies destructive commands in read-only mode.
- File snapshots are created and undo restores content.
- Streaming providers produce stable event order.
- Session JSONL can replay into final history.
- `occ exec --json` emits valid JSON lines.
- Hooks can allow, deny, and modify tool results.
- Scheduled task fires and persists across resume when expected.

Also add end-to-end tests with a fake provider that scripts:

- text-only response
- tool call then response
- denied tool call
- multiple tool calls
- streaming deltas
- subagent spawn
- provider error/retry

## Documentation Improvements

Docs should separate "implemented" from "planned". Right now the README claims
some features that are only partial or unwired.

Update docs to include:

- Accurate feature status table.
- Security model and permission modes.
- Tool approval behavior.
- Config reference with every field and whether it is currently honored.
- Plugin guide only after plugins are wired.
- MCP support matrix.
- Automation guide for `occ exec`.
- Scheduler guide for `/loop` and `/remind`.
- Git/GitHub workflow guide.
- Troubleshooting guide.
- Architecture docs with event flow diagrams.

## Recommended Next 10 Pull Requests

1. Fix MCP tool wrapper and add tests.
2. Add runtime tool policy and enforce read-only plan mode.
3. Add file snapshots and colorized diffs for write/edit.
4. Add `ProviderUsage`, usage events, and `/cost`.
5. Add streaming provider protocol and UI token rendering.
6. Add session JSONL transcripts and `/resume`.
7. Add `occ exec` with final stdout and progress stderr.
8. Add `--json` event output and structured final output option.
9. Wire `PluginMiddleware` and hook dispatch.
10. Add `/loop`, `/remind`, and task persistence.

If the goal is to become "the best AI coding agent available", do these before
new UI surfaces. Trust, safety, automation, and resumability are the foundation
that every advanced feature depends on.
