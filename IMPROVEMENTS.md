# OCC improvement roadmap

Audited 2026-09-12 against the checked-in source and tests, not README claims.
Compared with Claude Code, Codex CLI, and the usual coding-agent feature set.
OpenClaude ([Gitlawb/openclaude](https://github.com/Gitlawb/openclaude)) was
audited 2026-09-13 against that repo's `main` (TypeScript/Bun, ~v0.30, 1208
commits). Steal product ideas from it. Do not copy its source. It originated
from Claude Code.

**Implemented** means wired into the normal CLI path. **Partial** means the
core exists but hardening, UX, or tests are missing. **Broken** means the
code or docs promise something a user will hit and fail. **Missing** means
no end-to-end implementation.

The order of this file is the order of work. Fix what we already ship before
adding providers, and finish providers before chasing IDE, scheduler, or
marketplace features. OpenClaude takeaways slot into Waves 2–4. They do not
become a fifth wave that delays Groq, MCP HTTP, or `/cost`.

---

## How to use this file

Each item names the gap, why it matters, and where to start. Do not mark an
item implemented until it is on the CLI path and covered by a regression
test.

Tackle in four waves:

1. Make the current agent trustworthy. Slash commands, safety, exec, docs.
2. Make providers first-class. Groq hardening, `occ doctor`, `/provider`,
   Ollama native API, local tool-call recovery.
3. Finish the extension layer we already advertise. MCP, skills, plugins,
   subagents, hooks, sessions.
4. Add modern coding-agent workflows. Review, git mutation, LSP, background
   work, scheduler, IDE.

Wave 1 is done. Wave 2 is the current work. OpenClaude's first-run wizard
and Ollama native path belong here, not in a later "parity" wave.

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
| Providers | Partial | Anthropic, OpenAI-compat, Gemini, Groq, Ollama, OpenRouter. YAML parses `base_url`. Groq is `groq/` prefix-only. Compat hosts fall back `max_tokens` / drop `include_usage` on 400. No `/provider`, no `occ doctor`. Ollama uses the OpenAI shim. |
| MCP | Partial | Stdio tools are callable. Env is merged with `os.environ`. JSON-RPC/`isError` fail. No HTTP, resources, prompts, OAuth. |
| Plugins | Partial | Lifecycle hooks load at startup. No tools, slash commands, isolation, or packaging. |
| Skills | Implemented | Catalog then on-demand load. `allowed_tools` and `scripts/` are unused. No `/<skill-name>` slash. |
| Subagents | Implemented | Built-in explore/plan/GP, background wait/kill/steer, resume, worktrees, personas, `run_workflow` barriers. Child planning store is isolated. No Rhai workflow dialect or TUI tasks pane. |
| Hooks | Partial | Trusted `occ.yml` command hooks. Prompt/HTTP/MCP/agent hooks missing. Post-hooks ignore failure. |
| Sessions | Partial | JSONL ledger, resume, rename, export. No `--continue` or fork. Plan/skills/compaction not restored. Token deltas bloat the file. |
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
| `llama-*` even with `GROQ_API_KEY` | Anthropic (use `groq/` prefix) |
| anything else | Anthropic |

### Gaps that actually bite

1. **Done.** `openrouter/<vendor>/<model>` and `vendor/model` + `OPENROUTER_API_KEY`
   route to OpenRouter. `groq/` and `ollama/` still win. Explicit `base_url`
   still wins over the vendor/model heuristic.
2. **Done.** YAML parses `base_url`. Raw `api_key` is still not written to
   session snapshots.
3. **Done.** OpenRouter uses `OPENROUTER_API_KEY` or `--api-key`, plus
   `HTTP-Referer` / `X-Title`.
4. **Done.** Groq is prefix-only (`groq/…`). Unprefixed `llama-*` /
   `mixtral-*` / `gemma-*` / `deepseek-*` are not stolen when
   `GROQ_API_KEY` is set.
5. OpenAI/Groq/Ollama `stream()` requests `include_usage` and retries
   without it on 400. Reasoning still dropped on the OpenAI stream path.
   Anthropic `stream()` `done` also ships empty usage. `/status` and any
   future `/cost` will show zeros on that path.
6. **Done.** OpenAI-compat tries `max_completion_tokens`, then
   `max_tokens` on 400, and remembers which one the host accepted.
7. Anthropic enables extended thinking for every model whose name contains
   `"claude"`. Haiku and older snapshots 400.
8. No `list_models()`. No `occ doctor`. No `/provider` wizard. First run is
   still "export a key and hope the model string maps."
9. `ProviderStreamEvent` is a second stream vocabulary no provider emits.
10. Ollama goes through the OpenAI-compat shim at `localhost:11434/v1`.
    OpenClaude dropped that path because Ollama's shim silently truncates
    same-session history. They call Ollama's native chat API and set
    `num_ctx` (default 32768).
11. Local and GLM/Qwen models often emit tool calls as XML or text instead of
    function-call JSON. OpenClaude recovers those. We treat the text as the
    final answer and stop.
12. No per-model `context_window` / `max_output_tokens` overrides. A 8k local
    model still gets OCC's 16k default.

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

- **Done.** Prefer the `groq/` prefix. Unprefixed `llama-` / `mixtral-` /
  `gemma-` / `deepseek-` heuristic is gone.
- **Done.** `stream_options.include_usage`; drop and retry on 400.
- **Done.** Dual `max_tokens` / `max_completion_tokens` fallback on 400.
- **Done.** README lists current Groq ids. The wrapper default
  `llama-3.3-70b-versatile` will still rot; the prefix is the stable part.
- **Done.** Tool-calling rejection returns a clear `ProviderError`.

### Shared provider work in the same wave

- Fill usage on every `done` / `message_complete` (Anthropic final message
  still empty; OpenAI `include_usage` with 400 fallback is done).
- Stop forcing Anthropic thinking on every `claude*` name. Gate on a
  config flag or a known-model list.
- Unify on `StreamEvent`. Delete or actually emit `ProviderStreamEvent`.
- Narrow `_stream_response`'s `except Exception: send()` so programmer
  errors are not swallowed.
- `occ doctor`: which keys are set, which provider the model string maps
  to, Ollama reachable, `rg` present. OpenClaude's `doctor:runtime` also
  emits JSON and a persistable report. Match that shape so CI can consume it.
- `/provider` wizard that writes a user-level profile (`~/.occ/profiles.yml`
  or similar), not a session snapshot. Keys stay out of the JSONL ledger.
  Switching providers mid-session must not rewrite `occ.yml` in the project
  unless the user asks.
- Ollama native chat API plus `num_ctx`. Keep the OpenAI-compat wrapper as
  fallback for LM Studio / vLLM.
- Recover XML / text-shaped tool calls from local and GLM/Qwen models before
  treating the turn as a plain-text Stop. This is the difference between
  "Ollama can code" and "Ollama prints a fake function call and quits."
- OpenRouter (and any OpenAI-compat host that serves `/models`): optional
  live catalog for `/model`. Cache it. Do not hit the network every turn.
- Per-model `context_window` and `max_output_tokens` in YAML.

Provider profiles (fast / strong / local) wait until Wave 4. One working
OpenRouter path beats a routing DSL. A `/provider` wizard that saves the
path you already have is Wave 2, not a new SDK.

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
- `tools/list` pagination (`nextCursor`). OpenClaude shipped this. Fake
  stdio server tests should cover a two-page list.
- Per-server and per-tool policy. Today MCP tools are blocked in
  `read-only` (not on the allowlist) and unrestricted in
  `workspace-write`. That is crude. OpenClaude strips blanket-denied tools
  from the schema before the model sees them (`mcp__server` prefix deny
  drops that server's tools at pool assembly, not only at call time).
- Tool-schema lazy load. Claude Code and OpenClaude defer full MCP schemas
  until use, then expose a `ToolSearch` tool. We inject every schema every
  turn.
- MCP resources (`resources/list`, `resources/read`). OpenClaude has
  `ListMcpResources` / `ReadMcpResource`. Tools-only MCP is not a complete
  client.
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
  Claude Code and OpenClaude merged custom commands into skills. OpenClaude
  treats `SKILL.md` files as prompt-type commands the model can also invoke
  by name.
- `occ skills list|show|validate|install|remove`. OpenClaude pins registry
  installs with sha256, refuses revoked ids, and can verify later with a
  lockfile. We do not need their Skill Hub. We do need validate-on-load
  (reject `curl | sh` and credential-harvest wording) and a content hash
  recorded at install so a later edit is visible.
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

**Implemented.** Built-in `explore` / `plan` / `general-purpose` roles,
project `.occ/agents` files that can shadow them, personas from
`.occ/personas`, background spawn + `wait_agent` / `kill_agent` /
`send_agent_message`, `resume_from` on a completed child of the same
type, `isolation=worktree` plus `apply_agent_worktree`, and
`run_workflow` phase barriers (8 jobs/phase, 32/workflow). Children get
their own `PlanningMiddleware`. Nested spawn is still stripped. Default
blocking spawn is unchanged.

Not in this runtime: a Rhai workflow dialect, a TUI tasks pane, or
automatic merge of conflicting worktree edits beyond file copy.

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
  compact. Add `/compact` as an on-demand command, not only the automatic
  threshold. OpenClaude also refuses to micro-compact when compaction is
  off, and keeps a cooldown so auto-compact cannot thrash.
- `/init` that writes `AGENTS.md` from a repo walk (languages, test
  command, layout). Memory files the user never creates stay empty.

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

| Feature | Claude Code / Codex / OpenClaude | OCC now |
| --- | --- | --- |
| CLAUDE.md / AGENTS.md | Always-on, nested, user+project, `/init` | Project-dir files, 8k cap, no walk |
| Skills | `/name`, auto-invoke, scripts, install+hash | Catalog + `load_skill` |
| Subagents | Explore/Plan/GP, nest, worktrees, background, `maxSteps` | Explore/Plan/GP, worktrees, background, no nest |
| MCP | stdio + streamable HTTP, OAuth, resources, tool search | stdio tools |
| Hooks | command, HTTP, MCP, prompt, agent | command only |
| Plugins | bundle + marketplace | local `plugin.py` hooks |
| Headless exec | first-class, `--bg` process sessions | `occ exec`, untested defaults |
| Review / commit / PR | `/review`, `/bughunter`, `/commit` | read-only git + `/changes` |
| Permission modes | suggest / auto / full, session allow | three modes, exec flags |
| Sandbox | OS sandbox | regex + roots |
| LSP / diagnostics | goToDefinition, references, hover, symbols | grep |
| Repo map | tree-sitter + PageRank, `/repomap` | none |
| Background shell | `run_in_background`, notify on complete | blocking `run_shell` |
| Cost | `/cost` with model breakdown and cache | events, no UI |
| Scheduler | cron tools, `/loop`, GitHub Action | none |
| IDE | VS Code, gRPC app server | terminal only |
| Worktrees / best-of-N | yes | worktrees yes; no best-of-N picker |
| Images / notebooks / browser | clipboard paste, NotebookEdit, optional browser | no |
| Continue / fork session | `--continue`, `--fork-session` | `--resume <id>` only |
| Structured questions | `AskUserQuestion` multi-choice | freeform only |
| Provider setup | `/provider` wizard, saved profiles | env + YAML + heuristics |

We do not need all of this to be a good terminal agent. We do need the
ones that make daily coding possible: review, commit, tests after edit,
cost, interrupt, background long commands, continue-last-session, and a
provider wizard that does not require reading the README.

### Add, in this order

1. **`/cost` and per-run budgets.** Usage events already exist once stream
   `done` carries tokens. Price table in code, `/cost`, optional
   `max_budget_usd` that stops the loop. Show per-model input/output/cache
   tokens, API duration, and lines added/removed. Unknown-model prices must
   say so instead of printing `$0.00`.
2. **`--continue` and `--fork-session`.** Resume the most recent session
   for this cwd without pasting an id. Fork copies history into a new
   session id. Fork is conversation branching only, not a worktree.
3. **`/review` and `occ review`.** Read-only git tools plus a reviewer
   prompt. JSON for CI. No mutation. `/bughunter` can wait. One honest
   review command beats three prompt aliases.
4. **Git mutation behind policy.** `git_commit`, `/commit`, then `/pr`.
   Never implicit. `full-access` or an explicit git-write allow.
5. **REPL permission modes** matching exec: `suggest` / `auto` /
   `full-access`, plus "always allow this tool this session."
6. **Interrupt.** Ctrl+C cancels the in-flight provider or shell turn
   without killing the REPL. After interrupt, inject a short "the user
   stopped you, here is what they said next" so the model does not resume
   the aborted tool plan blindly. Today Ctrl+C exits the process.
7. **Background `run_shell`.** `run_in_background=true` returns a handle,
   notifies on complete, stores output as a session artifact. Stream
   stdout into the TUI. Do not make the model poll with `sleep`.
8. **Background agent runs.** `occ exec --bg "…"`, then `occ ps`,
   `occ logs <id> -f`, `occ kill <id>`. Local child processes, same
   policy flags as foreground exec. Metadata under `~/.occ/bg-sessions/`.
   This is not a daemon and not a substitute for `spawn_agent`.
9. **Quality gate `/verify`.** Format, targeted tests, typecheck. Natural
   hook point: `stop` / `post_edit`. OpenClaude's verification agent is
   the same idea with a dedicated child role.
10. **Repo map, then LSP.** A ranked file+signature summary (tree-sitter,
    import graph, PageRank, disk cache by mtime) so the first turn is not
    ten greps. Then `definition` / `references` / `hover` / `diagnostics`.
    After grep ignores and structured grep output, not before.
11. **`AskUserQuestion`.** Multiple-choice (with Other) when the model
    needs a decision mid-run. Plan mode should use this for approach
    choices, not for "does the plan look good?"
12. **Best-of-N on worktrees.** Built-in explore/plan/GP and worktrees
    already exist. What is left is picking a winner and merging it.
13. **Per-agent model routing and `maxSteps`.** Explore on a cheap model,
    plan on a strong one, cap a child's tool steps and force a summary
    when the cap hits. Same-provider model swap first. Cross-provider
    children wait until `/provider` profiles exist.
14. **Smart routing (optional).** Heuristic simple vs strong model per
    user turn, held for the whole turn, fallback to strong on transport
    error. Off by default. `/cost` should show simple/strong counts.
15. **Images and notebooks.** Clipboard paste (Ctrl+V / Alt+V on Windows)
    for vision models. `notebook_edit` for `.ipynb` cells. Optional
    Firecrawl key for JS-rendered `read_url`. No browser driver until
    DNS pinning lands.
16. **Scheduler** (`/loop`, `/remind`, `/tasks`) and a GitHub Action that
    wraps mature `occ exec --json`. Same runner. No second loop.
17. **`occ` as an MCP server** so other agents can call us. After our
    client works.
18. **IDE / app server.** Last. OpenClaude's VS Code extension and gRPC
    server sit on a complete exec path. Ours does not yet. A VS Code
    extension on a flaky exec path is a support queue.

Explicitly later (or never, unless someone asks): computer-use desktop,
voice, cross-session messaging, plugin marketplace, JetBrains, pixel
companions, ads, stickers, and a first-class class per partner gateway.

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

## OpenClaude takeaways (audited 2026-09-13)

Source: [Gitlawb/openclaude](https://github.com/Gitlawb/openclaude) `main`.
TypeScript/Bun CLI, npm `@gitlawb/openclaude`, ~33k stars, ~9k forks,
~1208 commits, current release around 0.30.0 (2026-08-31). Originated from
the Claude Code codebase and then forked hard toward multi-provider use.
MIT covers their modifications. The derived Claude Code remains Anthropic's.

OCC is a clean-room Python agent. OpenClaude is a Claude Code descendant
with a provider bazaar glued on. Copy the product moves that make a
terminal agent usable on day one. Do not copy `src/`, do not add their
partner catalog, and do not grow a feature-flag soup (`KAIROS`,
`PROACTIVE`, `COORDINATOR_MODE`, and friends).

Their daily-path wins are setup, session continuity, cost, background
work, repo intelligence, and local-model honesty. Their marketing surface
(pixel buddy, ads, stickers, twenty named gateways, VS Code, gRPC) is
what a 33k-star fork can afford. We cannot, and should not, chase it.

### What we already do better

Keep these. OpenClaude is not ahead here.

- Capability-first `ToolPolicy` before approval. Their permission system is
  large and still has prototype-key bugs in the changelog. Ours is small
  and fail-closed.
- File snapshots, unified diffs, and `/undo`. They edit in place.
- Child `permission_mode` clamped to the parent. Nested spawn stripped.
- UI-independent `agent.py` plus `EventBus`. Their `main.tsx` is 200k+
  characters. Swapping a UI or running `occ exec` does not require Ink.
- `apply_patch`, `multi_edit`, and `run_workflow` phase barriers.
- Honest Wave 1 docs. Their README still sells a companion sprite next to
  the coding agent.

### Side-by-side (only the steal-worthy rows)

| Area | OpenClaude | OCC | Steal? |
| --- | --- | --- | --- |
| First-run setup | `/provider` wizard, saved user profiles, `doctor:runtime` JSON | env vars + YAML + model-name heuristics | Yes, Wave 2 |
| Ollama | Native chat API, `num_ctx` 32768 | OpenAI-compat shim at `:11434/v1` | Yes, Wave 2 |
| Local tool calls | Recovers GLM/Qwen XML/text function calls | Text becomes the final answer | Yes, Wave 2 |
| Cost | `/cost`: USD, per-model tokens, cache, duration, lines, routing tally, custom prices | `UsageUpdated` events, `/status` has no dollars | Yes, Wave 2/4 |
| Sessions | `--continue`, `--fork-session`, `/rewind`, `/replay`, `/compact` | `--resume <id>`, `/clear` does not record a ledger event | Yes, Wave 3/4 |
| Detached runs | `openclaude --bg`, `ps`, `logs -f`, `kill` | none (subagents can background, the whole CLI cannot) | Yes, Wave 4 |
| Shell | `run_in_background`, notify on complete, PowerShell tool, command semantics | blocking `run_shell`, timeout kills the process group | Yes, Wave 4 |
| Skills | `/name` slash + model invoke, `skills install` with sha256, validate, verify | catalog + `load_skill` | Yes, Wave 3 |
| MCP | resources, OAuth, pagination, deny-from-schema, ToolSearch | stdio tools only | Yes, Wave 3 |
| Code intel | Repo map (tree-sitter + PageRank), LSP tool | grep / glob | Yes, Wave 4 |
| Questions | `AskUserQuestion` multi-choice + Other | freeform REPL | Yes, Wave 4 |
| Plan mode | `EnterPlanMode` / `ExitPlanMode` tools, read-only until exit | `/plan` one-shot, git tools omitted, not a real sandbox | Partial, Wave 3 |
| Review | `/review`, `/bughunter`, `/security-review`, built-in code-reviewer | `/changes` + read-only git | `/review` only, Wave 4 |
| Agents | per-agent model routing, `maxSteps`, verification child | explore/plan/GP, worktrees, no per-child model | Yes, Wave 4 |
| Images | clipboard paste, resize, 20-image cap handling | none | After web DNS pin |
| IDE | VS Code extension, headless gRPC | terminal | No, last |
| Buddy / ads / stickers | yes | no | Never |

### Concrete takeaways, grouped

**Provider UX (Wave 2).** `/provider` is the feature people actually use.
It writes a user-level profile, discovers models from `/models` where the
host allows it, and fails fast on placeholder keys. Pair it with `occ
doctor` that prints which key is set, which registry route the model
string takes, whether Ollama answers, and whether `rg` is on PATH. JSON
output for CI. OpenClaude's PLAYBOOK is a local-Ollama runbook. We should
have the same page once doctor exists, not a second architecture.

**Ollama is a protocol, not a base_url.** Their changelog is explicit:
the OpenAI shim drops history. Call `/api/chat`, send `num_ctx` (config
or `OCC_OLLAMA_NUM_CTX`), and keep the shim for everything else. This is
a correctness fix, not a new provider SDK.

**Local models lie about tool calling.** OpenClaude parses XML / text
tool calls from GLM and Qwen before giving up. Without that, `ollama/
qwen2.5-coder` looks broken in OCC even when the weights are fine. Put
the recovery in `providers/openai.py` (or a small post-processor) so Groq
and vLLM benefit too.

**Cost is a product, not an event.** `/cost` should show total USD, input
vs output vs cache bars, per-model rows, wall vs API duration, and lines
changed. Restore those totals on `--resume`. Custom YAML prices for
unknown slugs. Print "price unknown" rather than `$0.00`. Optional
`max_budget_usd` stops the loop. Smart-routing savings belong here if we
add routing later.

**Session verbs people type without looking up an id.** `--continue`
resumes the latest session for this cwd. `--fork-session` copies history
to a new id. `/compact` is a command, not only a threshold. `/rewind`
rolls conversation and file snapshots together (we already have the
snapshots). `/clear` must write a ledger event. Group forked sessions in
`/sessions`.

**Two kinds of background, both missing.** (1) A shell command that
returns a handle and notifies when it finishes. (2) A whole `occ exec`
detached from the terminal (`--bg` / `ps` / `logs` / `kill`). Do not
conflate them with `spawn_agent`. OpenClaude stores bg metadata under
`~/.openclaude/bg-sessions/` and treats vanished processes as `stale`
instead of guessing. Copy that honesty, including on Windows where they
refuse to infer POSIX signal names.

**Repo map before LSP.** OpenClaude builds a ranked signature list
(git ls-files, tree-sitter for TS/JS/Python, IDF-weighted import graph,
PageRank, mtime cache under `~/.openclaude/repomap-cache/`). Auto-inject
is opt-in and capped (~1024 tokens). `/repomap` and a `repo_map` tool
are always available. Cold build on a large repo is 20–30s. Cached is
under 100ms. That is the right shape: optional injection, on-demand
tool, disk cache. Then LSP (`goToDefinition`, `findReferences`,
`hover`, `documentSymbol`, diagnostics with burst coalescing).

**Skills are commands.** A `SKILL.md` should be invocable as
`/<skill-name>` and as a model tool. `occ skills validate` should reject
`curl | sh` and credential-collection wording. Registry installs (if we
ever have one) need sha256 and a revocation list. Until then, hash the
file at first load and warn on drift. Enforce `allowed_tools` as a
narrowing, never an elevation.

**MCP: stop at tools-only.** Add `resources/list` + `resources/read`,
`nextCursor` pagination, and deny-from-schema. ToolSearch when the
combined built-in + MCP list is large, so we stop stuffing every schema
into every turn. OAuth is after streamable HTTP. OpenClaude paginated
discovery in 0.29.0. We still talk to a stub manager in tests.

**Ask, then plan.** `AskUserQuestion` (multi-choice, always an Other,
optional preview for mockups) is how they stop the model from guessing
architecture. Plan mode is read-only until `ExitPlanMode`. Our `/plan`
one-shot is fine for v1. The missing piece is a real read-only policy
for that mode, plus a structured question tool so "which approach?" is
not a wall of prose.

**Interrupt is a turn, not an exit.** Ctrl+C should abort the in-flight
provider stream or shell and leave the REPL up. OpenClaude then injects
correction context so the next message is not interpreted as
continuation of the killed tool plan. They also watch for repeated tool
failures (doom loop) and warn before stopping. We have `max_turns`. We
do not have "the same edit failed three times."

**Agent routing without a sixth SDK.** `agentModels` + `agentRouting` in
user settings: Explore on a cheap model, Plan on a strong one, optional
`maxSteps` that forces a summary. Same provider, different model id.
Cross-provider children wait for `/provider` profiles. Smart routing
(simple vs strong per user turn, held for the whole turn, fallback to
strong on transport errors, off by default) is the same mechanism with
a heuristic chooser.

**Windows is a first-class runtime.** This repo is developed on Windows.
OpenClaude has a PowerShell tool, Windows clipboard bitmap paste via
.NET `Clipboard.GetImage()`, EPERM tolerance on drive-root mkdir, and
dedicated Windows quick-start docs. `run_shell` should not pretend it is
always bash. Image paste can wait. Shell semantics cannot.

**Small-model preset.** OpenClaude's `CLAUDE_CODE_SIMPLE` exposes only
Bash, Read, and Edit. Worth a config flag for Ollama so a 7B model is
not handed 25 schemas.

**Prompt-cache hygiene.** They keep built-in tools as a contiguous,
name-sorted prefix and append MCP tools after, so a new MCP server does
not bust the Anthropic cache breakpoint. We already send prompt-cache
headers. Tool list order should be stable for the same reason.

**Stream hang safety.** Watchdog on stalled provider streams, visible
retries, headless heartbeat for print/exec mode so CI does not look
wedged. Cheap, and they added it because it actually hangs.

### What not to take from OpenClaude

- Pixel-art buddy, ads, stickers, dream, chrome, voice, mobile QR,
  knowledge-graph wiki. Entertainment, not an agent loop.
- A first-class class per partner gateway (Z.AI, Concentrate, LLMTR,
  ApiSmart, ClinePass, LongCat, NEAR, Atlas, …). OpenRouter plus
  `--base-url` plus `/provider` profiles covers them. Descriptors are
  how *they* survived 20 vendors. We do not have 20 vendors.
- VS Code extension and gRPC server. After `occ exec` is boring and
  `--bg` works.
- Plugin marketplace. After plugins fail loudly and MCP can start `npx`
  on Windows.
- Hook-chains that spawn fallback agents on failure. Cool, also a
  fork-bomb if the cooldown is wrong. Finish `post_edit` honoring
  failure first.
- Team/swarm coordinator, REPL-in-a-VM, cron tools, remote bridge.
  After scheduler and background shell.
- Copying their TypeScript. License and architecture both say no.

### Mapping onto the PR list

OpenClaude does not change the wave order. It names the next tickets
inside waves we already have:

| After PR | Add |
| --- | --- |
| 12 (Groq) | XML/text tool-call recovery. Ollama native + `num_ctx`. |
| 13 (`doctor` + `/cost`) | `/provider` wizard + saved profiles. `/cost` model breakdown. Live `/models` for OpenRouter. |
| 14 (skills) | `/<skill-name>` slash. `occ skills validate`. Hash-at-load drift warning. |
| 16 (sessions) | `--continue`, `--fork-session`, `/compact`, `/clear` ledger event. |
| 17 (MCP HTTP) | resources, pagination, deny-from-schema, ToolSearch. |
| 18 (`/review`) | Keep one review command. Skip `/bughunter` until review is used. |
| 20 (interrupt + bg shell + `/verify`) | `occ exec --bg` / `ps` / `logs` / `kill`. Doom-loop detector. |
| later | Repo map, LSP, `AskUserQuestion`, agent model routing, `maxSteps`, images. |

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
   "do not steal `deepseek-*`" **Done** (PR 12).
6. MCP env merge + JSON-RPC error → `ToolResult.fail`. **Done**.
7. Shell `unknown` under `workspace-write`. **Done**.
8. `git_branch` output shape.
9. Session `/clear` vs resume.
10. Hook `OCC_FILE_PATH` on `post_edit`.

A fake provider that scripts text, tool, deny, multi-tool, stream, spawn,
and 429-retry is worth more than another unit test of `estimate_tokens`.
**Done** (`tests/fakes.py`, `tests/test_agent_scenarios.py`).

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
| 12 | Groq heuristic removal, `include_usage`, max_tokens fallback. | 2 (done) |
| 13 | `occ doctor` + `/cost` from real usage. | 2 |
| 14 | Skills: enforce `allowed_tools`, expose scripts, fix `list_skills` lie. | 3 |
| 15 | Subagent isolation (own middleware), built-in explore/plan roles. | 3 (done) |
| 16 | Session: no per-token ledger, persist plan, `/clear` is real. | 3 |
| 17 | MCP streamable HTTP + per-server policy. | 3 |
| 18 | `/review` + `occ review --json`. | 4 |
| 19 | Git commit/PR behind explicit policy. | 4 |
| 20 | Interrupt + background shell + `/verify`. | 4 |
| 21 | XML/text tool-call recovery for OpenAI-compat and Ollama. | 2 |
| 22 | Ollama native chat API + `num_ctx`. | 2 |
| 23 | `/provider` wizard, user-level saved profiles, no keys in the ledger. | 2 |
| 24 | `--continue` latest cwd session + `--fork-session`. | 3 |
| 25 | Skills as `/<name>` commands + `occ skills validate`. | 3 |
| 26 | `occ exec --bg` / `ps` / `logs` / `kill`. | 4 |
| 27 | Repo map tool + optional auto-inject. | 4 |
| 28 | `AskUserQuestion` + plan-mode read-only until explicit exit. | 4 |

PRs 1–12 landed. Wave 2 continues at PR 13 (`occ doctor` + `/cost`).
OpenClaude does not jump the queue. PRs 21–23 ride with Wave 2. 24–25
with Wave 3. 26–28 with Wave 4.

---

## What not to do yet

- Do not add another provider SDK (xAI, Together, Fireworks, Z.AI,
  Concentrate, LongCat, …) as a full class. OpenRouter or `--base-url`
  covers them. Unprefixed unknown slugs still default to Anthropic. A
  `/provider` profile is a YAML stanza, not a new module under
  `providers/`.
- Do not copy OpenClaude source. It is a Claude Code descendant. Steal
  behavior, write Python.
- Do not build a VS Code extension or a gRPC server on top of an exec
  path that prompts Y/n.
- Do not add a plugin marketplace before plugins can fail loudly and MCP
  can start `npx`.
- Do not add computer-use or a browser driver while `read_url` still
  TOCTOU-resolves DNS.
- Do not add a pixel companion, ads, stickers, or a skill hub. Those are
  how a 33k-star fork fills a README. They are not why people run a
  coding agent.
- Do not treat README checkboxes as done. This file is the status board.

The skeleton is good: provider protocol, event bus, middleware, policy
before approval, snapshots, sessions. The gap is not "more architecture."
It is that several advertised paths do not run, several safety claims are
regex, OpenRouter was a flag instead of a provider, and first run still
asks you to export the right env var from memory.
