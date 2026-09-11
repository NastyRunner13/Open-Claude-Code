# OCC improvement roadmap

Audited 2026-09-12 against the checked-in source and tests, not README claims.
Compared with Claude Code, Codex CLI, and the usual coding-agent feature set.

**Implemented** means wired into the normal CLI path. **Partial** means the
core exists but hardening, UX, or tests are missing. **Broken** means the
code or docs promise something a user will hit and fail. **Missing** means
no end-to-end implementation.

The order of this file is the order of work. Fix what we already ship before
adding providers, and finish providers before chasing IDE, scheduler, or
marketplace features.

---

## How to use this file

Each item names the gap, why it matters, and where to start. Do not mark an
item implemented until it is on the CLI path and covered by a regression
test.

Tackle in four waves:

1. Make the current agent trustworthy. Slash commands, safety, exec, docs.
2. Make providers first-class. OpenRouter, Groq hardening, Gemini follow-up.
3. Finish the extension layer we already advertise. MCP, skills, plugins,
   subagents, hooks, sessions.
4. Add modern coding-agent workflows. Review, git mutation, LSP, background
   work, scheduler, IDE.

Wave 1 is not optional. Several documented commands do not run. Several
safety claims are only true for the happy path.

---

## Status at a glance

| Area | Status | What is true today |
| --- | --- | --- |
| Agent loop | Implemented | Tool loop, policy-before-approval, retries, streaming consumption, `max_turns`. One loop (`_legacy_run_streaming` removed). |
| Ask / plan / agent modes | Partial | `/plan <task>` and `/agent <task>` route to one-shot modes. `/agent list` lists roles. Plan git tools still omitted. |
| Built-in file tools | Implemented | Roots, snapshots, unified diffs, undo for write/edit/multi-edit/patch. Unbound tools fail closed. |
| Shell | Partial | `workspace-write` denies unknown and destructive. Process-group kill on timeout. No background, no output stream. |
| Web | Partial | Public-IP check and redirect revalidation exist. DNS is not pinned. Search ignores domain policy. |
| `sandbox` tool | Partial | Schema and README no longer claim a jail. Still a subprocess with timeout only. |
| Providers | Partial | Anthropic, OpenAI-compat, Gemini, Groq, Ollama, OpenRouter. YAML parses `base_url`. Stream `done` now carries usage. Gemini function-response names are correct. Anthropic thinking is opt-in. |
| MCP | Partial | Stdio tools are callable. Env is merged with `os.environ`. JSON-RPC/`isError` fail. No HTTP, resources, prompts, OAuth. |
| Plugins | Partial | Lifecycle hooks load at startup. No tools, slash commands, isolation, or packaging. |
| Skills | Implemented | Catalog then on-demand load. `allowed_tools` and `scripts/` are unused. Schema no longer mentions `list_skills()`. |
| Subagents | Partial | Parallel spawn, roles, default read-only. Child mode is clamped to the parent. Shared middleware still. |
| Hooks | Partial | Trusted `occ.yml` command hooks. Prompt/HTTP/MCP/agent hooks missing. Post-hooks ignore failure. |
| Sessions | Partial | JSONL ledger, resume, rename, export. Plan/skills/compaction not restored. Token deltas bloat the file. |
| `occ exec` | Implemented | Non-interactive default (deny privileged). Missing task exits 2. `--quiet` honored. CLI tests cover argv and approval. |
| Memory files | Partial | Loads `AGENTS.md` / `CLAUDE.md` from configured dirs only. No parent walk, no write-back. |
| Planning checklist | Partial | In-memory `write_plan` / `update_plan` / `read_plan`. Lost on resume. |
| Git | Partial | Read-only status/diff/log/branch. `git_branch` argv is wrong. No commit/PR/review. |
| Cost / usage UI | Missing | `UsageUpdated` is emitted from stream `done`. No `/cost`. |
| Docs vs code | Implemented | README, CHANGELOG, schemas, and MCP docstring match the Wave 1 code. |

---

## Wave 1. Fix what we currently have

These are user-visible failures or safety holes in code that already ships.

### 1. Slash commands that do not do what `/help` says

**Implemented.** `/plan <task>` and `/agent <task>` route to one-shot modes.
`/plan` / `/plan show|clear|progress` stay checklist commands. `/agent list`
lists roles. Covered by `tests/test_cli.py`.

### 2. `occ exec` is not safe for CI as documented

**Implemented.** Default exec denies privileged tools. Missing task exits 2.
`--quiet` suppresses non-final JSON events. `--approval-mode auto` still
auto-approves policy-permitted calls. CLI tests cover argv, JSON final, and
suggest/auto approval.

### 3. Child agents can raise their own privilege

**Implemented.** Child `permission_mode` is clamped to the parent. Spawn
approval shows `task` and `permission_mode`. Nested `spawn_agent` remains
stripped. Test: a child requesting `full-access` stays at the parent cap.

### 4. `sandbox` is not a sandbox

**Implemented (honest docs).** Schema and README no longer claim a
filesystem or network jail. Timeout is still the only isolation. A real
jail (job object / bubblewrap / seatbelt) is later work.

### 5. Dead code that bypasses policy

**Implemented.** `_legacy_run_streaming` deleted. `run_streaming()` wraps
`run()`.

### 6. Streaming UI prints the answer twice

**Implemented.** Live tokens win: `Stop` skips the markdown panel when
`StreamTextDelta` already printed the answer. `AgentStart` is emitted at
the start of `run()`.

### 7. Gemini tool follow-up is invalid

**Implemented.** `functionResponse.name` is the declaration name, looked up
from the prior `tool_use` id. Anthropic thinking is opt-in for known
thinking models. Stream `done` carries usage.

### 8. Docs that lie

**Implemented.** README, CHANGELOG, `load_skill` schema, MCP docstring, and
`save_config` comments match the code.

### 9. Shell policy is bypassable

**Implemented (Wave 1 bar).** `workspace-write` denies `unknown` and
destructive shell in both `ToolPolicy` and `ToolContext`. Timeouts kill the
process group. Approval shows the command. Tests cover bypass strings
(`rm file`, `git checkout -- .`, `python -c`, `curl | sh`).

### 10. MCP `env` replaces the whole process environment

**Implemented.** Env is `os.environ.copy()` plus server extras. Stderr is
drained. JSON-RPC `error` and `isError` map to `ToolResult.fail`. Dual
Content-Length / NDJSON remains Wave 3.

---

## Wave 2. Providers: OpenRouter, Groq, and the ones we already have

Groq already exists as a thin OpenAI-compat wrapper. OpenRouter is a first-class
wrapper of `OpenAIProvider`. Remaining Wave 2 work is Groq hardening, usage on
every path, `occ doctor`, and `/cost`.

Do not add a sixth SDK. Keep wrapping `OpenAIProvider` for OpenAI-compat
hosts. Put provider-specific auth, headers, and model-id rules in small
wrappers and in the registry.

### What works today

| Input | Result |
| --- | --- |
| `claude-*` | Anthropic |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*`, `chatgpt-*` | OpenAI |
| `gemini-*` | Gemini (optional extra) |
| `groq/llama-3.3-70b-versatile` | Groq |
| `openrouter/anthropic/claude-sonnet-4` | OpenRouter, sends `anthropic/claude-sonnet-4` |
| `anthropic/claude-…` with `OPENROUTER_API_KEY` | OpenRouter |
| `ollama/llama3.2` | Ollama at localhost:11434 |
| `--base-url` or YAML `base_url` | OpenAI-compat, needs `--api-key` or `OPENAI_API_KEY` |
| `llama-*` with `GROQ_API_KEY` set | Groq (heuristic) |
| anything else | Anthropic |

### Gaps that actually bite

1. **Done.** `openrouter/<vendor>/<model>` and `vendor/model` + `OPENROUTER_API_KEY`
   route to OpenRouter. `groq/` and `ollama/` still win. Explicit `base_url`
   still wins over the vendor/model heuristic.
2. **Done.** YAML parses `base_url`. Raw `api_key` is still not written to
   session snapshots.
3. **Done.** OpenRouter uses `OPENROUTER_API_KEY` or `--api-key`, plus
   `HTTP-Referer` / `X-Title`.
4. Groq unprefixed heuristic steals `deepseek-*` / `llama-*` whenever
   `GROQ_API_KEY` is in the environment.
5. OpenAI/Groq/Ollama `stream()` drops usage and reasoning. Anthropic
   `stream()` `done` also ships empty usage. `/status` and any future
   `/cost` will show zeros on the live path.
6. OpenAI always sends `max_completion_tokens`. Older vLLM / some Groq /
   some Ollama builds want `max_tokens`.
7. Anthropic enables extended thinking for every model whose name contains
   `"claude"`. Haiku and older snapshots 400.
8. No `list_models()`. No `occ doctor`.
9. `ProviderStreamEvent` is a second stream vocabulary no provider emits.

### OpenRouter (implemented)

`providers/openrouter.py`, thin wrap of `OpenAIProvider`:

```
base_url: https://openrouter.ai/api/v1
api_key:  OPENROUTER_API_KEY or --api-key
headers:  HTTP-Referer, X-Title (OCC GitHub URL)
```

Registry:

- `openrouter/<vendor>/<model>` strips the `openrouter/` prefix and sends
  `<vendor>/<model>` to OpenRouter.
- `openrouter/<model>` for OpenRouter-native ids.
- If `OPENROUTER_API_KEY` is set and the model looks like `vendor/model`
  (contains `/` and is not `groq/` or `ollama/`), route to OpenRouter
  instead of Anthropic.

Config:

- YAML `base_url` is parsed (raw `api_key` is still never persisted into
  session snapshots).
- Optional `providers:` profiles later. Not required for this PR.

Tests: registry routing, prefix strip, missing-key error, header defaults.
Do not hit the live API in CI.

### Groq (harden, do not rewrite)

Keep the wrapper. Then:

- Prefer the `groq/` prefix. Drop or tightly scope the unprefixed
  `llama-` / `mixtral-` / `gemma-` / `deepseek-` heuristic.
- `stream_options.include_usage` so usage is not zero.
- Dual `max_tokens` / `max_completion_tokens` fallback on 400.
- Document current Groq model ids in README. The wrapper default
  `llama-3.3-70b-versatile` will rot.
- Tool-calling is model-dependent. If a Groq model rejects tools, return a
  clear `ProviderError`, not a generic OpenAI exception.

### Shared provider work in the same wave

- Fill usage on every `done` / `message_complete` (Anthropic final message,
  OpenAI `include_usage`).
- Stop forcing Anthropic thinking on every `claude*` name. Gate on a
  config flag or a known-model list.
- Unify on `StreamEvent`. Delete or actually emit `ProviderStreamEvent`.
- Narrow `_stream_response`'s `except Exception: send()` so programmer
  errors are not swallowed.
- `occ doctor`: which keys are set, which provider the model string maps
  to, Ollama reachable, `rg` present.

Provider profiles (fast / strong / local) wait until Wave 4. One working
OpenRouter path beats a routing DSL.

---

## Wave 3. Finish the extension layer we already advertise

### MCP

What works: stdio connect, `tools/list`, namespaced `mcp_{server}_{tool}`
wrappers that return `ToolResult`, `/mcp list|add|remove`, shutdown.

Still missing or weak:

- Merge env (Wave 1).
- Streamable HTTP. SSE is spec-deprecated after 2025-03-26; implement HTTP,
  not the old SSE transport, unless a server still needs it.
- Resources and prompts.
- OAuth / headers for remote servers.
- `tools/list` pagination (`nextCursor`).
- Per-server and per-tool policy. Today MCP tools are blocked in
  `read-only` (not on the allowlist) and unrestricted in
  `workspace-write`. That is crude.
- Tool-schema lazy load. Claude Code defers full MCP schemas until use.
  We inject every schema every turn.
- Dual Content-Length / NDJSON reader.
- Tests against a fake stdio server that speaks the real wire format, not
  only a stub `MCPManager`.

Do not add a plugin marketplace until MCP against `@modelcontextprotocol/server-filesystem`
works on Windows and Unix.

### Skills

What works: discovery of `SKILL.md`, catalog in the prompt, `load_skill`,
`disable_model_invocation`, `/skill load|unload|reload`.

Finish:

- Enforce `allowed_tools` when a skill is loaded (narrow, do not elevate).
- Surface `scripts/`, `examples/`, `assets/` paths in the injected prompt
  so the model can `read_file` / `run_shell` them. Do not auto-exec.
- Slash invocation `/<skill-name>` or `/skill run <name>`, matching how
  Claude Code merged custom commands into skills.
- Fix the `list_skills()` schema lie. **Done** (Wave 1).
- Malformed skills should log, not `pass`.

### Plugins

What works: `plugin.py` `register(hooks)` for start / before-send /
after-response / tool-result / stop. `/plugin list|reload`.

Finish:

- `/plugin reload` must re-emit `on_agent_start`.
- Load failures must be visible, not swallowed.
- A small manifest (`plugin.yml`: name, description, version) so listing
  does not require importing Python.
- Optional `get_tools()` from a plugin, behind the same `ToolPolicy`.
- No isolation story yet. Treat plugins as trusted local code, same as
  hooks. Say that in the README. Marketplace comes later.

Claude Code plugins bundle skills + hooks + MCP + agents. That packaging
is Wave 4. First make the Python hook runtime honest.

### Subagents

What works: concurrent `asyncio.gather`, role files in `.occ/agents/*.md`,
model / tool allowlist / `permission_mode` / `max_turns`, nested spawn
stripped, optional child session.

Finish after the Wave 1 elevation fix:

- Do not share the parent's `MiddlewareManager`. A child that can
  `update_plan` is mutating the parent's checklist because
  `write_plan` / `update_plan` are in `READ_ONLY_TOOLS`.
- Built-in roles: `explore` (read-only), `plan` (read-only + plan tools),
  `general-purpose` (parent cap). Claude Code ships these; we make the
  user invent `.occ/agents`.
- Resume a child session from the parent ledger.
- Truncation at 12k is fine; say so in the schema.
- Schema text currently says children auto-approve everything. After the
  clamp, rewrite it.

Worktrees, background children, and nesting wait for Wave 4.

### Hooks

What works: `pre_tool`, `pre_<tool>`, `post_edit`, `post_tool`, `stop` as
trusted shell commands from `occ.yml`.

Finish:

- Honor `post_edit` / `stop` failures or document them as fire-and-forget.
  Today only pre-hooks can veto.
- Pass `OCC_FILE_PATH` on `post_edit`. The example config uses it.
  `on_tool_result` currently sends `tool_name` and `tool_use_id` only.
- Matcher on tool name (glob), not only `pre_run_shell` as a separate key.
- Prompt / HTTP / MCP-tool hook types are Claude Code parity. Command
  hooks that actually receive the file path are enough for Wave 3.

### Sessions, memory, planning

Sessions already persist history, tool calls, usage, retries. Resume
reloads history and original model/mode.

Finish:

- `/clear` must record a ledger event so resume does not resurrect the
  conversation.
- Do not persist every `token_delta`. That file grows without bound and
  stores thinking traces. Keep usage totals and final messages.
- Redact `tool_params` values, not only config key names. A
  `write_file` of `.env` is currently stored in plaintext.
- Persist `PlanStore` in the session (or a sidecar JSON). Resume is
  incomplete without it.
- Memory: walk parents for `AGENTS.md` / `CLAUDE.md`, then a user-level
  `~/.occ/AGENTS.md`. Cap remains. Nested dir files can load when a
  tool touches that tree (Claude Code behavior). Not required for the
  first memory PR.
- Compaction: record a `history_compacted` event; repair
  `tool_use` / `tool_result` pairing so Anthropic does not 400 after
  compact.

### Tools that are already registered but wrong or thin

- `git_branch`: `git branch --show-current --all` does not list branches.
  Split current vs `--list` or drop `--show-current`.
- `grep_search`: add `--glob` tests, `-C` context, kill `rg` on timeout,
  pass `max_output` on the Python fallback.
- `find_files` / `list_directory`: default-ignore `.git`, `.venv`,
  `node_modules`, `__pycache__`, `.occ`.
- `web_search`: run DDGS off the event loop; apply allow/block lists to
  result URLs.
- `read_url`: pin the resolved IP (or connect by IP with Host header) to
  close DNS rebinding. Convert HTML with a real readability/markdown
  path, or stop calling it markdown.
- Planning tools should return `ToolResult`, same as everything else.
- Unbound tools (`_context is None`) fail closed (Wave 1).

---

## Wave 4. Modern coding-agent features

Only after Waves 1–3. These are the features people mean when they say
"like Claude Code / Codex."

### Comparison (what they have, what we have)

| Feature | Claude Code / Codex | OCC now |
| --- | --- | --- |
| CLAUDE.md / AGENTS.md | Always-on, nested, user+project | Project-dir files, 8k cap, no walk |
| Skills | `/name`, auto-invoke, scripts, fork | Catalog + `load_skill` |
| Subagents | Explore/Plan/GP, nest, worktrees, background | Parallel spawn, roles, no nest |
| MCP | stdio + streamable HTTP, OAuth, tool search | stdio tools |
| Hooks | command, HTTP, MCP, prompt, agent | command only |
| Plugins | bundle + marketplace | local `plugin.py` hooks |
| Headless exec | first-class | `occ exec`, untested defaults |
| Review / commit / PR | `/review`, `codex review` | read-only git + `/changes` |
| Permission modes | suggest / auto / full, session allow | three modes, exec flags |
| Sandbox | OS sandbox | regex + roots |
| LSP / diagnostics | code intelligence plugins | grep |
| Background shell | yes | blocking `run_shell` |
| Cost | `/cost` | events, no UI |
| Scheduler | `/loop`, GitHub Action, automations | none |
| IDE | VS Code, app server | terminal only |
| Worktrees / best-of-N | yes | none |
| Images / notebooks / browser | yes | no |

We do not need all of this to be a good terminal agent. We do need the
ones that make daily coding possible: review, commit, tests after edit,
cost, interrupt, background long commands.

### Add, in this order

1. **`/cost` and per-run budgets.** Usage events already exist once stream
   `done` carries tokens. Price table in code, `/cost`, optional
   `max_budget_usd` that stops the loop.
2. **`/review` and `occ review`.** Read-only git tools plus a reviewer
   prompt. JSON for CI. No mutation.
3. **Git mutation behind policy.** `git_commit`, `/commit`, then `/pr`.
   Never implicit. `full-access` or an explicit git-write allow.
4. **REPL permission modes** matching exec: `suggest` / `auto` /
   `full-access`, plus "always allow this tool this session."
5. **Interrupt.** Ctrl+C cancels the in-flight provider or shell turn
   without killing the REPL.
6. **Background `run_shell`.** Return a handle, notify on complete, store
   output as a session artifact. Stream stdout into the TUI.
7. **Quality gate `/verify`.** Format, targeted tests, typecheck. Natural
   hook point: `stop` / `post_edit`.
8. **LSP tool.** `definition`, `references`, `diagnostics` after edits.
   This is how modern agents stop grepping for symbols. After grep
   ignores and structured grep output, not before.
9. **Built-in explore/plan/general-purpose subagents.** Then worktrees for
   best-of-N attempts.
10. **Scheduler** (`/loop`, `/remind`, `/tasks`) and a GitHub Action that
    wraps mature `occ exec --json`. Same runner. No second loop.
11. **`occ` as an MCP server** so other agents can call us. After our
    client works.
12. **IDE / app server.** Last. A VS Code extension on a flaky exec path
    is a support queue.

Explicitly later (or never, unless someone asks): computer-use desktop,
voice, cross-session messaging, plugin marketplace, JetBrains.

### Provider marketplace (after OpenRouter works)

```yaml
providers:
  fast:
    type: groq
    model: groq/llama-3.3-70b-versatile
  strong:
    type: openrouter
    model: openrouter/anthropic/claude-sonnet-4
  local:
    type: ollama
    model: ollama/qwen2.5-coder
```

Then `planner_model`, `editor_model`, `summarizer_model`. Compaction and
hooks should use the cheap profile. Do not build this until the registry
no longer sends unknown slugs to Anthropic.

---

## Testing gaps that block every wave

The suite is strong on `Agent.run`, tools with tmp paths, EventBus, config
file load, and provider registry. It barely touches the CLI.

Add, in order:

1. `handle_slash_command` for `/plan <task>`, `/agent <task>`, `/agent list`,
   `/plan show`. **Done** (`tests/test_cli.py`).
2. `occ exec` argv: missing task, `--json` final event, `--approval-mode
   suggest` denies writes, `--ephemeral` writes nothing. **Done**.
3. Child `permission_mode` clamp. **Done**.
4. Gemini `functionResponse.name`. **Done**.
5. OpenRouter registry cases. **Done** (`tests/test_providers.py`). Groq
   "do not steal `deepseek-*`" remains PR 12.
6. MCP env merge + JSON-RPC error → `ToolResult.fail`. **Done**.
7. Shell `unknown` under `workspace-write`. **Done**.
8. `git_branch` output shape.
9. Session `/clear` vs resume.
10. Hook `OCC_FILE_PATH` on `post_edit`.

A fake provider that scripts text, tool, deny, multi-tool, stream, spawn,
and 429-retry is worth more than another unit test of `estimate_tokens`.

CI already runs pytest on 3.12/3.13. Keep it. Add a Windows job before
claiming MCP `npx` examples work. This repo is developed on Windows.

---

## Suggested pull requests

Small, reviewable, in this order. One concern each.

| # | PR | Wave |
| --- | --- | --- |
| 1 | Fix `/plan` and `/agent` routing. Tests for `handle_slash_command`. | 1 (done) |
| 2 | Delete `_legacy_run_streaming`. One agent loop. | 1 (done) |
| 3 | Exec: non-interactive default, missing-task exit, honor or drop `--quiet`. CLI tests. | 1 (done) |
| 4 | Clamp child `permission_mode`. Show spawn params in approval. | 1 (done) |
| 5 | Honest `sandbox` description. Fail-closed unbound tools. | 1 (done) |
| 6 | Stop double-printing stream + `Stop`. Emit `AgentStart` or drop it. | 1 (done) |
| 7 | Gemini function-response name. Anthropic thinking opt-in. Stream usage on `done`. | 1 (done) |
| 8 | MCP env merge, stderr drain, RPC errors as failures. | 1 (done) |
| 9 | Docs pass: README, CHANGELOG, `load_skill` schema, MCP docstring. | 1 (done) |
| 10 | Shell: deny `unknown` in `workspace-write`, process-group kill, command in approval prompt. | 1 (done) |
| 11 | First-class OpenRouter provider + YAML `base_url`. | 2 (done) |
| 12 | Groq heuristic removal, `include_usage`, max_tokens fallback. | 2 |
| 13 | `occ doctor` + `/cost` from real usage. | 2 |
| 14 | Skills: enforce `allowed_tools`, expose scripts, fix `list_skills` lie. | 3 |
| 15 | Subagent isolation (own middleware), built-in explore/plan roles. | 3 |
| 16 | Session: no per-token ledger, persist plan, `/clear` is real. | 3 |
| 17 | MCP streamable HTTP + per-server policy. | 3 |
| 18 | `/review` + `occ review --json`. | 4 |
| 19 | Git commit/PR behind explicit policy. | 4 |
| 20 | Interrupt + background shell + `/verify`. | 4 |

PRs 1–11 landed. Wave 2 continues at PR 12 (Groq hardening).

---

## What not to do yet

- Do not add another provider SDK (xAI, Together, Fireworks) as a full
  class. OpenRouter or `--base-url` covers them. Unprefixed unknown slugs
  still default to Anthropic.
- Do not build a VS Code extension on top of an exec path that prompts
  Y/n.
- Do not add a plugin marketplace before plugins can fail loudly and MCP
  can start `npx`.
- Do not add computer-use or a browser driver while `read_url` still
  TOCTOU-resolves DNS.
- Do not treat README checkboxes as done. This file is the status board.

The skeleton is good: provider protocol, event bus, middleware, policy
before approval, snapshots, sessions. The gap is not "more architecture."
It is that several advertised paths do not run, several safety claims are
regex, and OpenRouter is a flag instead of a provider.
