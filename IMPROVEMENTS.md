# OCC Improvement Roadmap and Implementation Audit

This document reviews Open Claude Code (OCC) against current Codex and Claude
Code capabilities, then maps those product ideas onto this codebase. It is
intentionally implementation-oriented: each recommendation names the current
gap, why it matters, and where to start.

## Implementation Status (audited 2026-07-12)

Status in this document is based on the checked-in source and regression
tests, not on planned work or README claims. **Implemented** means a feature
is wired into the normal CLI runtime. **Partial** means the core is present but
important capability, hardening, or UX work remains. **Planned** means no
end-to-end implementation was found.

| Area | Status | Evidence / remaining boundary |
| --- | --- | --- |
| MCP stdio tool calls | Implemented | Bound async MCP wrappers return `ToolResult`; only stdio transport is supported. |
| Plugin lifecycle | Implemented | Plugins load at startup and receive start, before-send, after-response, tool-result, and stop hooks; there is no plugin packaging or isolation model. |
| Plan safety | Implemented | Plan generation receives an allowlisted, read-only tool registry; execution restores the full registry after explicit approval. |
| Runtime tool policy | Implemented | `ToolPolicy` is non-bypassable and supports `read-only`, `workspace-write`, `full-access`, and disallowed-tool patterns. |
| File safety and reversible edits | Implemented | Bound filesystem tools enforce roots; writes, edits, multi-edits, and patches create snapshots, return unified diffs, and support undo. |
| Shell and web safety | Partial | Coarse shell classification, workspace cwd validation, public-HTTP(S) validation, cache, and prompt-injection wrapping exist; no command segmentation, process-tree cleanup, or DNS/IP revalidation. |
| Provider streaming and resilience | Implemented | Normalized stream events, token/tool/usage events, typed transient errors, and retry/backoff are wired; cost calculation and a user-facing `/cost` command are absent. |
| Durable sessions | Partial | JSONL history/tool ledger, resume, list, rename, export, redacted config snapshots, and nested subagent sessions exist; file/approval/change events are not yet a complete task capsule. |
| Automation CLI | Implemented | `occ exec`, JSON Lines, output schema validation, last-message output, ephemeral mode, and sandbox/approval flags are implemented. |
| Hooks | Partial | Trusted command hooks can run before tools, after tools/edits, and at stop; prompt, HTTP, MCP, agent, notification, and transcript-capture hooks are not implemented. |
| Git workflow | Partial | Read-only `git_status`, `git_diff`, `git_log`, `git_branch`, and `/changes` exist; review, commit, PR, and GitHub workflows do not. |
| Skills | Implemented | Discovery exposes only metadata; full instructions load on demand, and the loader supports `disable_model_invocation`, `allowed_tools`, scripts, examples, and assets. |
| Subagents | Partial | Named role definitions, explicit models/tool allowlists/policies/max turns, isolated histories, sessions, and concurrent execution exist; worktrees, persistent memory, background tasks, and management UX are pending. |

### Immediate priorities after this audit

1. Harden the existing safety primitives: command segmentation and process
   cleanup, DNS/IP validation for web access, and policy coverage for MCP and
   plugins.
2. Complete the observable automation path: cost reporting, richer session
   events, command-output streaming, and robust `occ exec` integration tests.
3. Build the missing developer workflows: review/commit/PR support, scheduler,
   durable tasks, and GitHub Actions.

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

1. Finish safety hardening around the implemented tools: segmented shell
   policy, process cleanup, web DNS/IP validation, and MCP/plugin policy.
2. Turn usage and session foundations into an observable automation product:
   `/cost`, complete task evidence, command streaming, and CLI integration
   coverage.
3. Build scheduled and GitHub automation on top of the existing `occ exec`
   JSONL path rather than creating a parallel execution model.
4. Add review and explicit Git workflows before expanding autonomous mutation.
5. Improve code intelligence and advanced subagent orchestration after the
   trust, automation, and review layers are complete.

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
- MCP stdio client with callable tool wrappers.
- Plugin runtime with lifecycle hook dispatch and `/plugin list|reload`.
- LLM-based context compaction that respects `context_compaction`.
- Non-bypassable agent-level tool policy with configurable modes and deny rules.
- Durable local session metadata and JSONL ledger, including CLI resume and
  session listing.
- Token-streaming Rich/prompt-toolkit terminal UI.
- Tests for core agent loop, providers, tools, config, planning, memory,
  skills, middleware, events, and context.

Still pending or only partially implemented:

- Cost/token accounting surfaced to the user (`/cost` and price tables).
- Complete task-capsule evidence: approvals, file changes/snapshots, provider
  deltas, plan updates, and a clear replay/export format.
- Command-output streaming, command segmentation, environment policy, and
  process-tree cleanup for shell execution.
- DNS/IP revalidation, robots/content policy, and fine-grained per-MCP and
  per-plugin capability policy.
- Scheduled tasks, reminders, monitors, and recurring loops.
- Review, commit, PR, GitHub, and worktree workflows.
- IDE integration and language-server code intelligence.
- Remote/browser/desktop control surfaces.
- Full MCP support: streamable HTTP, OAuth, server instructions, resources,
  prompts, elicitation, and per-tool policy.

## Important Codebase Issues To Fix

This section preserves the original implementation targets, but each item is
now marked with the observed state so it can be used as a working backlog.

### 1. MCP Tools Are Registered With No Callable Function — Implemented

File: `src/open_claude_code/mcp/client.py`

`MCPManager.get_occ_tools()` now assigns a bound async caller per discovered
tool. It routes to the correct server and returns `ToolResult`; regression
coverage invokes a fake server through the OCC wrapper.

Remaining work:

- Add streamable HTTP transport, authentication, server instructions,
  resources/prompts/elicitation, and per-tool policy/timeout controls.

Implemented wrapper shape:

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

### 2. Plugin System Is Documented But Not Wired Into The CLI — Implemented

Files:

- `src/open_claude_code/plugins/manager.py`
- `src/open_claude_code/main.py`
- `src/open_claude_code/config.py`
- `README.md`

`main.py` now installs `PluginMiddleware` in the runtime stack. It scans
configured directories at startup and dispatches `on_agent_start`,
`on_before_send`, `on_after_response`, `on_tool_result`, and `on_agent_stop`.
`/plugin list` and `/plugin reload` are available in the interactive CLI.

Remaining work:

- Add enable/disable state, a documented package/manifest format, tool schema
  registration, capability policy, and isolation for untrusted plugin code.

### 3. Plan Mode Is Prompt-Only Safe, Not Runtime-Enforced Safe — Implemented

Files:

- `src/open_claude_code/modes.py`
- `src/open_claude_code/agent.py`

Plan generation now replaces the normal registry with the explicit
`PLAN_GENERATION_TOOLS` allowlist. It includes exploration and plan tools only;
the full registry is restored only after user approval for execution.

Keep covered:

- Preserve regression coverage for attempts to call write/edit/shell tools
  while the planning registry is active.

### 4. `context_compaction` Config Is Ignored — Implemented

Files:

- `src/open_claude_code/config.py`
- `src/open_claude_code/agent.py`

`Agent.run()` now calls automatic compaction only when the config is absent or
`context_compaction` is true. A regression test verifies the disabled case.

Remaining work:

- Improve compaction quality metrics and preserve structured task evidence when
  long histories are summarized.

### 5. `max_tool_output` Config Is Ignored — Implemented

Files:

- `src/open_claude_code/config.py`
- `src/open_claude_code/tools/*.py`

The runtime binds a `ToolContext` from `AgentConfig`; built-in tools take its
`max_output` rather than their legacy standalone defaults. Tests cover the
configurable truncation path.

Remaining work:

- Extend context-bound limits and artifact storage to MCP, plugin, and long
  shell outputs.

### 6. File Tools Need A Workspace Sandbox — Implemented

Files:

- `src/open_claude_code/tools/read_file.py`
- `src/open_claude_code/tools/write_file.py`
- `src/open_claude_code/tools/edit_file.py`
- `src/open_claude_code/tools/list_directory.py`
- `src/open_claude_code/tools/find_files.py`
- `src/open_claude_code/tools/grep_search.py`

Runtime-bound file tools resolve paths and restrict reads to `workspace_roots`
and writes to `writable_roots`. Denials emit `ToolDenied` events, and glob
results are filtered back through the read policy.

Remaining work:

- Add explicit, auditable one-off elevation rather than relying solely on
  configuration changes for outside-root access.

### 7. Shell Tool Needs Structured Policy And Better Runtime Control — Partial

File: `src/open_claude_code/tools/run_shell.py`

The shell tool now has a coarse read/write/destructive classifier, policy modes,
workspace-validated cwd override, timeout, exit status, and output truncation.
Destructive commands are denied outside `full-access`; `read-only` denies
non-read commands.

Remaining work:

- Parse every command segment, control environment/network access, stream
  stdout/stderr, terminate the full process tree on timeout, and save long logs
  as session artifacts.

### 8. `read_url` And `web_search` Need Web Safety Controls — Partial

Files:

- `src/open_claude_code/tools/read_url.py`
- `src/open_claude_code/tools/web_search.py`

Runtime web access now requires public HTTP(S), supports domain allow/block
lists and network disablement, limits response bytes, caches results, and wraps
web/search content as untrusted. `fetch_public_url` rejects unsafe resolved
addresses before returning content.

Remaining work:

- Add DNS-rebinding protection across redirects, robots/content policy,
  provenance-aware source selection, and a maintained dependency strategy for
  search.

### 9. Provider Abstraction Lacks Streaming, Usage, Retries, And Structured Errors — Implemented

Files:

- `src/open_claude_code/providers/base.py`
- `src/open_claude_code/providers/*.py`
- `src/open_claude_code/agent.py`

`ProviderResponse` now carries usage and metadata; providers expose normalized
streams and typed errors. The agent emits token, tool-call, usage, and provider
failure events, records stream/usage events in sessions, and retries transient
429/5xx-style failures with exponential backoff.

Remaining work:

- Add price-aware cost calculation, budget controls, and provider-specific
  safety/error metadata where the upstream API exposes it.

### 10. OpenAI Provider Should Move Toward The Responses API — Planned

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

### 11. Subagents Are Useful But Too Coarse — Partial

Files:

- `src/open_claude_code/tools/spawn_agent.py`
- `src/open_claude_code/subagents/manager.py`

Subagents default to read-only and cannot recurse. They can now use a named
`.occ/agents/*.md` role with system instructions, model, tool allowlist,
disallowed tools, permission mode, and max turns. They have isolated history,
an event bus, optional nested durable sessions, and concurrent execution.

Remaining work:

- Add memory scopes, direct resume/management UX, background tasks, worktree
  isolation, and configurable result summarization rather than fixed truncation.

### 12. Skills Load Too Much Context — Implemented

Files:

- `src/open_claude_code/skills/loader.py`
- `src/open_claude_code/middleware/skills.py`

Skill discovery parses frontmatter without instructions, exposes a compact
catalog, and loads the full `SKILL.md` only through `load_skill` or `/skill`.
Frontmatter supports invocation control, allowed tools, and optional resource
directories.

Remaining work:

- Add namespaced plugin skills and enforce `allowed_tools` rather than treating
  that field as descriptive metadata.

### 13. Session History Has A Durable Baseline, Not A Full Task Capsule — Partial

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
| Streaming responses | Supported | Implemented: token, thinking, tool, and usage events | P1 |
| Diffs and syntax highlighting | Supported | Unified diffs after OCC edits; syntax highlighting/review pending | P1 |
| File snapshots / undo | Rollback via transcript/git workflow patterns | Implemented for OCC write/edit/multi-edit/patch operations | P1 |
| Runtime permission modes | Sandbox/approval modes | Implemented: capability modes + path/shell policy | P1 |
| Durable sessions / resume | Supported | Local JSONL + CLI resume, list, rename, export; richer evidence pending | P1 |
| MCP | Richer transports/auth/instructions | Callable stdio tools; richer transports/auth/policy pending | P1 |
| Plugins | Packaging layer | Runtime hooks wired; packaging/sandboxing pending | P1 |
| Non-interactive mode | `codex exec`, `claude -p` | Implemented: `occ exec` | P1 |
| JSONL event stream | Supported by Codex exec | Implemented for `occ exec --json` | P1 |
| Scheduled tasks / loops | Claude `/loop`, scheduled tasks | No | P1 |
| Hooks | Claude hooks, Codex hooks/config | Trusted command hooks only | P1 |
| GitHub automation | GitHub Actions / PR workflows | No first-class support | P1 |
| Subagent orchestration | Custom agents, isolated contexts | Named roles, isolated context/session, concurrent spawn; no worktrees/background | P1 |
| Cost / token tracking | Exposed in automation outputs | Usage events present; costs and `/cost` missing | P1 |
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

OCC status: local JSONL history/tool ledgers, redacted config snapshots, cwd,
model/mode, config hash, CLI `--resume <session-id>`, `/sessions`, `/rename`,
and `/export` are implemented. Remaining work is named/last/all resume UX,
approval/plan/file-change evidence, and a stable replayable capsule format.

### Non-Interactive Automation

Codex `exec` is designed for scripts and CI, with final output on stdout,
progress on stderr, JSONL event mode, structured output schemas, and explicit
sandbox/approval settings.

OCC status: `occ exec`, `--json`, `--output-last-message`,
`--output-schema`, `--sandbox`, `--approval-mode`, and `--ephemeral` are
implemented. Remaining work is progress separation on stderr, structured exit
code/reporting conventions, durable scheduled tasks, and CI examples.

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

OCC has the core separation now: always-on memory, metadata-first/on-demand
skills, MCP stdio, custom subagent roles, command hooks, and runtime plugin
hooks. The next boundary is packaging and policy/isolation for extensions.

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

OCC status: `AgentRegistry` reads `.occ/agents/*.md`, and a spawned child can
select a named role with its model, tool allowlist, permission mode, and max
turns. Child histories and optional sessions are isolated. Remaining work is
role templates, memory, background jobs, worktrees, and richer management
commands.

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

**Status: substantially complete.** MCP wrappers, plugin lifecycle wiring,
plan allowlisting, compaction configuration, output limits, workspace roots,
and coarse shell policy are implemented and covered by focused tests. Keep the
remaining portability/documentation work in normal maintenance.

- [x] Fix MCP tool callable registration.
- [x] Wire plugins into the runtime.
- [x] Enforce read-only tool availability during plan generation.
- [x] Respect `context_compaction`.
- [x] Respect `max_tool_output`.
- [x] Add path sandboxing for all filesystem tools.
- [x] Add coarse structured shell policy.
- [x] Add regression tests for the implemented behavior.
- [ ] Fix README and `IMPROVEMENTS.md` encoding/emoji portability if Windows
  terminals remain a target.

### Phase 1: Trust Layer

Goal: users should feel safe letting OCC edit code.

**Status: core implementation complete; hardening remains.** Snapshots, undo,
unified diffs, multi-edit, unified patches, and capability modes are live.
Transaction preview/commit, immutable change events, and granular approval
rules are still planned.

- [x] Add file snapshots before every write/edit.
- [x] Add `/undo` and `undo_edit` tool.
- [x] Add unified diffs after edits (colorized display remains pending).
- [x] Add `multi_edit` and `apply_patch` tools.
- [ ] Add edit transaction grouping: start, preview diff, commit, rollback.
- [ ] Add immutable file-change events in transcripts.
- Add policy modes:
  - `read-only`
  - `suggest`
  - `workspace-write`
  - `full-access`
- [ ] Add per-tool and per-path approval rules.

### Phase 2: Streaming And Sessions

Goal: make OCC feel fast and professional.

**Status: partial.** Provider streaming, token/tool/usage events, JSONL
history, `/status`, `/sessions`, CLI resume, `/rename`, `/export`, and retry
backoff are implemented. `/cost`, cost calculation, complete structured
transcripts, and command-output streaming remain.

- [x] Add provider streaming and token/tool/usage events.
- [ ] Add command output streaming.
- [x] Add local JSONL transcripts, `/status`, `/sessions`, CLI `--resume`,
  `/rename`, and `/export`.
- [ ] Add `/cost` and usage/cost accounting for all providers.
- [x] Add retry/backoff and provider-failure events.

### Phase 3: Automation Runtime

Goal: make OCC useful outside an interactive terminal.

**Status: partial.** `occ exec`, `--json`, `--output-last-message`,
`--output-schema`, `--ephemeral`, sandbox selection, and approval-mode flags
are implemented. Scheduling, durable task storage, GitHub Actions, and
notification hooks remain.

- [x] Add `occ exec`.
- [x] Add `--json` event stream.
- [x] Add structured output schema.
- [x] Add `--output-last-message`.
- [x] Add `--ephemeral`.
- Add scheduler:
  - `/loop`
  - `/remind`
  - `/tasks`
  - task SQLite store
- [ ] Add GitHub Action.
- [x] Add trusted command hook runtime.
- [ ] Add notification hooks.

### Phase 4: Git And Review Workflows

Goal: make daily coding workflows first-class.

**Status: started.** Read-only Git inspection and `/changes` are implemented;
all mutation, review, PR, CI, and worktree workflows remain planned.

- Add tools:
  - [x] `git_status`, `git_diff`, `git_log`, `git_branch`
  - [ ] `git_commit`, `git_stash`, `git_apply_patch`
- Add slash commands:
  - [ ] `/review`, `/commit`, `/pr`, `/branch`
  - [x] `/changes`
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

**Status: started.** Custom role definitions, policy/tool constraints,
isolated child sessions, and concurrent fan-out are implemented. Memory,
background execution, worktrees, coordinator strategy, and verification agents
remain planned.

- [x] Add custom agent definitions.
- [ ] Add subagent memory.
- [x] Add isolated subagent transcripts/sessions (direct resume is pending).
- [ ] Add background agents.
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

### Add `ToolContext` — Implemented

Runtime-bound built-in tools now receive a context object. The implementation
contains workspace/writable roots, shell and web policy, output limits,
snapshot storage, session ID, and event bus (rather than the earlier proposed
`config`/`policy` fields directly).

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

### Add `ToolPolicy` — Implemented

`ToolPolicy` decides whether a tool is denied before approval is requested.
Approval itself remains the responsibility of the event bus/listener layer.

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

### Add `SessionStore` — Partial

The JSONL ledger and metadata snapshot are implemented. SQLite indexing and
task state are not.

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

### Add `ProviderStreamEvent` — Implemented

Provider responses and streams are normalized across Anthropic, OpenAI, Gemini,
Groq, and Ollama:

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

### Add `AutomationRunner` — Partial

`main.py` provides the current `occ exec` runner. A shared automation runner
for interactive scheduled tasks, cancellation, and durable task state remains
to be designed.

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

Completed quick wins:

- MCP callable registration, `--version`, `/status`, `git_diff`, unified
  edit/write diffs, file snapshots and undo, configurable `read_file`
  offset/limit/line numbers, `--quiet`, and non-interactive automation flags.

Best remaining small changes:

- Add default directory ignores for `.git`, virtual environments, dependency
  folders, builds, and caches.
- Display command timeout/exit status consistently in the TUI and stream long
  command output.
- Add shell and slash-command completion.
- Add `occ doctor` for API keys, provider availability, Git, MCP, and common
  dependency diagnostics.
- Add `/cost` from the existing usage events.

## Testing Improvements

Current tests cover many units, but the next phase needs integration and
behavior tests.

Already covered by focused regression tests:

- MCP callable wrappers; compaction disablement; output limits; root sandbox;
  shell policy; snapshots/undo; multi-edit/patch atomicity; stream usage and
  retry; session replay/rename/export; skills; custom-agent definitions; and
  plugin lifecycle wiring.

Add or strengthen tests for:

- Plan-mode denials from an actual model tool-call response, not just registry
  selection.
- Stable streaming event order for every provider implementation.
- `occ exec --json`, output-schema validation, and exit codes as CLI-level
  integration tests.
- Hook denial, timeout, stdout/stderr capture, and post-edit failure behavior.
- Shell segment classification and process-tree cleanup.
- Web redirect/DNS-rebinding defenses and cache-policy behavior.
- Scheduler persistence once scheduled tasks exist.

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

1. Add cost tables, `/cost`, per-run budgets, and provider usage integration
   tests.
2. Make shell policy segment-aware; add env/network controls and process-group
   cleanup.
3. Stream command stdout/stderr and persist long output as session artifacts.
4. Add redirect-safe DNS/IP validation plus web cache and domain-policy tests.
5. Record file changes, snapshots, approvals, plans, and provider metadata as
   complete structured session evidence.
6. Add `/review` and `occ review --json` using the existing read-only Git
   tools.
7. Add Git mutation workflows behind explicit policy/approval gates.
8. Introduce a scheduler with `/loop`, `/remind`, `/tasks`, and durable task
   storage.
9. Add a GitHub Action built on the mature `occ exec --json` path.
10. Add worktree-backed/background subagents and a verifier role after edits.

If the goal is to become "the best AI coding agent available", do these before
new UI surfaces. Trust, safety, automation, and resumability are the foundation
that every advanced feature depends on.
