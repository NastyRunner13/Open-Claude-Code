<div align="center">
  <h1>⚡ Open Claude Code (OCC)</h1>
  <p>
    <a href="https://github.com/NastyRunner13/Open-Claude-Code/actions"><img src="https://img.shields.io/github/actions/workflow/status/NastyRunner13/Open-Claude-Code/ci.yml?label=CI" alt="CI"></a>
    <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="License"></a>
  </p>
  <p><strong>An open-source, model-agnostic AI coding agent that lives in your terminal.</strong></p>
  <p>Works with <b>Claude</b> · <b>GPT</b> · <b>Gemini</b> · <b>Groq</b> · <b>Ollama</b> · <b>any OpenAI-compatible endpoint</b></p>
</div>

---

## Why OCC?

Most AI coding tools lock you into a single model, a single IDE, or a proprietary cloud. **Open Claude Code** gives you a fully local, terminal-native coding agent where *you* pick the brain.

- **Capability-first safety** — non-bypassable tool policy, workspace roots, shell controls, and subagents clamped to the parent
- **Durable session ledger** — locally persisted JSONL transcripts with run metadata and CLI resume

- 🧠 **Bring any model** — switch from Claude to GPT-4o to a local Llama with a single flag
- 🛠️ **25 built-in tools** — reversible file edits, code search, Git inspection, shell execution, web search, sandboxed Python, coordinated sub-agents, and more
- 🔌 **Extensible by design** — Skills (YAML+Markdown prompts), Python plugins, and MCP tool servers
- 📋 **3 interaction modes** — Ask (Q&A), Plan (review-then-execute), Agent (full autonomy)
- 🧩 **Composable middleware** — Memory, Planning, Skills, and MCP each plug in independently
- ⚡ **Context-aware** — automatic conversation compaction with LLM-powered summarization

---

## Table of Contents

- [Quick Start](#-quick-start)
- [Model Support](#-model-support)
- [Interaction Modes](#-interaction-modes)
- [Built-in Tools](#-built-in-tools)
- [Extensibility](#-extensibility-skills-plugins--mcp)
- [Architecture](#-architecture)
- [Configuration](#%EF%B8%8F-configuration)
- [Slash Commands](#-slash-commands)
- [Development](#-development)
- [Roadmap](#-roadmap)
- [License](#-license)

---

## 🚀 Quick Start

> **Requires Python 3.12+**

### Install from PyPI

```bash
pip install open-claude-code
```

### Or run from source with [uv](https://docs.astral.sh/uv/) (recommended for development)

```bash
git clone https://github.com/NastyRunner13/Open-Claude-Code.git
cd Open-Claude-Code
uv sync        # installs all dependencies
uv run occ     # launch the agent
```

### First run

Set your API key and go:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # or OPENAI_API_KEY, GEMINI_API_KEY, etc.
occ
```

You'll be greeted with an interactive REPL:

```
  ⚡ Open Claude Code v0.1.0
  ┌──────────────────────────────────────────────────┐
  │    ██████╗   ██████╗  ██████╗                    │
  │   ██╔═══██╗ ██╔════╝ ██╔════╝                    │
  │   ██║   ██║ ██║      ██║       claude-sonnet-4   │
  │   ╚██████╔╝ ╚██████╗ ╚██████╗  ⚡ agent · 16k   │
  │    ╚═════╝   ╚═════╝  ╚═════╝                    │
  └──────────────────────────────────────────────────┘
  ❯ _
```

---

## 🧠 Model Support

OCC auto-detects the right provider from the model name. No configuration needed.

```bash
# Anthropic (default)
occ --model claude-sonnet-4-20250514

# OpenAI
occ --model gpt-4o

# Google Gemini
occ --model gemini-2.0-flash

# Groq (prefix required — unprefixed llama-/deepseek- is not Groq)
occ --model groq/llama-3.3-70b-versatile
occ --model groq/llama-3.1-8b-instant
occ --model groq/openai/gpt-oss-120b

# OpenRouter (any catalog model; strips the openrouter/ prefix)
occ --model openrouter/anthropic/claude-sonnet-4

# Local models via Ollama
occ --model ollama/llama3.2

# Any OpenAI-compatible endpoint (Together, vLLM, etc.)
occ --model my-model --base-url https://api.together.xyz/v1
```

### Provider detection logic

| Model prefix | Provider | API Key env var |
|---|---|---|
| `claude-*` | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI | `OPENAI_API_KEY` |
| `gemini-*` | Google Gemini | `GEMINI_API_KEY` |
| `groq/*` | Groq (prefix required) | `GROQ_API_KEY` |
| `openrouter/*` | OpenRouter | `OPENROUTER_API_KEY` |
| `vendor/model` with `OPENROUTER_API_KEY` set | OpenRouter | `OPENROUTER_API_KEY` |
| `ollama/*` | Ollama (local) | — |
| `--base-url` / YAML `base_url` | OpenAI-compatible | `OPENAI_API_KEY` |

Groq model ids change; the `groq/` prefix does not. Current production examples:
`llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `openai/gpt-oss-120b`,
`openai/gpt-oss-20b`. Pass them as `groq/<id>`.

---

## 🎯 Interaction Modes

| Mode | Prompt | Description | When to use |
|------|:---:|-------------|-------------|
| **Ask** | `?` | Single LLM response, **no tools** | Quick questions, explanations, code reviews |
| **Plan** | `📋` | Creates a checklist → you review → agent executes | Refactors, multi-file changes, anything you want to verify first |
| **Agent** | `❯` | Full autonomous loop with tools | Complex tasks, debugging sessions, feature implementation |

Switch modes any time:

```
❯ /mode plan
  Mode: agent → plan

📋 Refactor the authentication module into separate files
  📋 Plan Mode — generating plan for your task...
```

### Plan Mode workflow

```
1. 📋 Agent explores codebase and creates a step-by-step plan
2. 👀 You review: approve (y), reject (n), or provide feedback to refine
3. ▶  On approval, agent executes each step autonomously
4. ✅ Reports completion
```

---

## 🧰 Built-in Tools

Every tool uses a clean schema that any supported LLM can call:

| Tool | Description | Auto-approved |
|------|-------------|:---:|
| `read_file` | Read file contents (with line limits) | ✅ |
| `write_file` | Create new files or overwrite existing ones | ❌ |
| `edit_file` | Surgical string replacement (old → new, must be unique) | ❌ |
| `multi_edit` | Apply several exact replacements atomically | ❌ |
| `apply_patch` | Validate and apply a unified diff atomically | ❌ |
| `undo_edit` | Restore a before-change OCC snapshot | ❌ |
| `list_directory` | List names; directories get a `/` suffix | ✅ |
| `find_files` | Glob-based file search | ✅ |
| `grep_search` | Ripgrep-powered code search (`rg -S`), with a Python fallback | ✅ |
| `run_shell` | Execute shell commands with output capture | ❌ |
| `web_search` | Search the web via DuckDuckGo | ✅ |
| `read_url` | Fetch a URL and strip HTML tags to plain text | ✅ |
| `sandbox` | Run Python in a subprocess (timeout only — not a filesystem/network jail) | ❌ |
| `spawn_agent` | Spawn a child (`explore` / `plan` / `general-purpose` or `.occ/agents`). Supports `background`, `isolation=worktree`, `resume_from`, `cwd`, `persona` | ❌ |
| `wait_agent` | Wait for one or more children, or snapshot with `timeout_ms=0` | ✅ |
| `kill_agent` | Cancel a running child | ❌ |
| `send_agent_message` | Steer a running child, or `queue=true` for a follow-up turn | ❌ |
| `apply_agent_worktree` | Copy a child's worktree files into the parent workspace | ❌ |
| `run_workflow` | Phase barrier: fan-out jobs in parallel, wait, next phase | ❌ |
| `load_skill` | Dynamically load skills to extend prompts | ✅ |
| `git_status`, `git_diff`, `git_log`, `git_branch` | Read-only Git inspection for review workflows | ✅ |

> **Auto-approved** tools run without prompting you. Configure this in `occ.yml` via `auto_approve`.

Every runtime file edit creates a session-scoped snapshot and returns a unified diff. Use `/undo path/to/file` to restore the latest snapshot, or use `/changes` to inspect the active Git diff. Set `persist_snapshots: false` to disable local snapshots.

### Safety model

`permission_mode` is an enforced capability boundary, not merely an approval preference. `read-only` permits exploration and read-only Git tools; `workspace-write` permits configured workspace changes, an allowlist of read/write shell commands, and rejects unknown or destructive shell; `full-access` is explicit opt-in. Filesystem roots, URL scheme/domain rules, public-IP checks, response limits, and network policy are applied before built-in tool execution. Tools invoked without a bound `ToolContext` fail closed. Web content is clearly marked as untrusted data before being returned to the model.

### Non-interactive automation

Use `occ exec` in CI or scripts. It prints the final response to stdout, writes progress as JSON Lines with `--json`, and respects the same sandbox and policy controls as the REPL. Privileged tools are denied unless `--approval-mode auto` or `--approval-mode full-access` is explicit. Missing `task` exits with code 2.

```bash
occ exec "Run the targeted tests and summarize failures" --sandbox read-only
occ exec "Implement the approved plan" --approval-mode auto --output-last-message result.md
occ exec "Return JSON release notes" --json --output-schema schema.json --ephemeral
occ exec "Summarize" --json --quiet
```

`--approval-mode suggest` (the default) denies non-auto-approved tool calls rather than waiting for a terminal prompt. `--quiet` keeps only the final `--json` event. `--ephemeral` leaves no session or snapshot artifacts.

---

## 🔌 Extensibility (Skills, Plugins, & MCP)

OCC is designed to be extended in three ways, from simplest to most powerful:

### 1. 📝 Skills — Prompt Extensions

Teach the agent new workflows by dropping a `SKILL.md` file into a skills directory. Skills are Markdown files with YAML frontmatter:

```yaml
# .occ/skills/pr-review/SKILL.md
---
name: PR Review Expert
description: Best practices for reviewing pull requests
---

When asked to review a PR, follow this workflow:
1. Check for test coverage — every changed function needs tests
2. Look for security issues — SQL injection, XSS, unvalidated inputs
3. Verify types — ensure all public functions have type annotations
4. Review naming — clear, descriptive names over abbreviations
```

```
❯ /skill load PR Review Expert
  Loaded skill: PR Review Expert
```

### 2. 🐍 Plugins — Python Lifecycle Hooks

For programmatic extensions, write Python plugins with hooks into the agent lifecycle:

```python
# .occ/plugins/my-logger/plugin.py
PLUGIN_NAME = "Custom Logger"

def register(hooks):
    async def on_tool_used(tool_name, **kwargs):
        print(f"🔧 Tool called: {tool_name}")

    hooks.on_tool_result(on_tool_used)
```

### 3. 🌐 MCP — Model Context Protocol

Connect external tool servers that speak the [Model Context Protocol](https://modelcontextprotocol.io/) standard over stdio:

```yaml
# In occ.yml
mcp_servers:
  - name: filesystem
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]

  - name: github
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "ghp_..."
```

Manage servers at runtime:

```
❯ /mcp list
  Connected MCP servers:
  • filesystem
  • github

❯ /mcp add sqlite npx -y @modelcontextprotocol/server-sqlite ./mydb.sqlite
  Successfully connected to sqlite and loaded 5 tools.
```

---

## 🏗 Architecture

OCC follows a clean, modular architecture with clear separation of concerns:

```
src/open_claude_code/
├── agent.py              # Core agent loop (no UI, pure logic + EventBus)
├── main.py               # CLI entry point, REPL, slash command routing
├── config.py             # YAML + env + CLI cascading configuration
├── context.py            # Token tracking + LLM-powered conversation compaction
├── modes.py              # Ask / Plan / Agent mode implementations
├── system_prompt.py      # Per-mode system prompts
│
├── providers/            # LLM provider abstraction layer
│   ├── base.py           # Provider protocol + response types
│   ├── registry.py       # Auto-detection factory (model name → provider)
│   ├── anthropic.py      # Claude (with prompt caching + extended thinking)
│   ├── openai.py         # GPT, o1, o3, o4, any OpenAI-compatible
│   ├── gemini.py         # Google Gemini via google-genai
│   ├── groq.py           # Groq cloud inference
│   ├── openrouter.py     # OpenRouter (OpenAI-compat + attribution headers)
│   └── ollama.py         # Local models via Ollama
│
├── tools/                # Tool definitions (schema + implementation)
│   ├── read_file.py      # File reading with line limits
│   ├── write_file.py     # File creation with parent dir auto-creation
│   ├── edit_file.py      # Surgical search-and-replace editing
│   ├── grep_search.py    # Ripgrep-powered code search
│   ├── find_files.py     # Glob-based file finding
│   ├── list_directory.py # Directory listing (names, dirs get `/`)
│   ├── run_shell.py      # Shell command execution
│   ├── web_search.py     # DuckDuckGo web search
│   ├── read_url.py       # URL fetching + HTML→markdown conversion
│   ├── sandbox.py        # Isolated Python execution
│   ├── spawn_agent.py    # Sub-agent spawn/wait/kill/steer/worktree/workflow schemas
│   ├── load_skill.py     # Runtime skill loading
│   └── result.py         # Structured ToolResult type
│
├── middleware/            # Composable feature injection
│   ├── __init__.py       # Middleware base class + MiddlewareManager
│   ├── mcp.py            # MCP server lifecycle + tool aggregation
│   ├── memory.py         # AGENTS.md / CLAUDE.md context file loading
│   └── skills.py         # Skill discovery + prompt injection
│
├── events/               # Event-driven architecture (decouples agent from UI)
│   ├── bus.py            # EventBus with typed event routing
│   └── types.py          # Event types (Thinking, PreToolUse, PostToolUse, etc.)
│
├── listeners/            # Event handlers (UI rendering, approval gates, logging)
│   ├── ui.py             # Rich-based terminal UI
│   ├── approval.py       # Tool approval prompts (y/n)
│   └── logging.py        # File-based logging
│
├── planning/             # Plan mode implementation
│   ├── middleware.py      # Planning middleware (tools + prompt additions)
│   ├── store.py          # Checklist state management
│   └── tools.py          # write_plan, update_plan, read_plan tools
│
├── skills/               # Skill discovery and management
├── plugins/              # Plugin system with lifecycle hooks
├── subagents/            # Sub-agent manager, built-in roles, personas, worktrees
└── mcp/                  # MCP client (server process management + tool bridging)
```

### Key design decisions

- **Event-driven core** — The agent loop (`agent.py`) contains zero UI code. Everything flows through the `EventBus`, making it trivial to swap the UI or run headlessly.
- **Composable middleware** — Each feature (MCP, Skills, Memory, Planning) is a `Middleware` subclass that independently injects tools, extends prompts, and hooks into lifecycle events.
- **Provider abstraction** — All LLM providers implement the same `Provider` protocol, making model-switching a one-line change.
- **Structured tool results** — Every tool returns a `ToolResult` with success/failure status and metadata, not raw strings.

---

## ⚙️ Configuration

OCC uses a cascading configuration system. Priority order:

**CLI flags** → **Environment variables** → **Config file** (`occ.yml` / `.occ/config.yml`)

### Environment Variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
export GROQ_API_KEY="gsk_..."
export OPENROUTER_API_KEY="sk-or-..."
export OCC_MODEL="gpt-4o"    # Override default model
```

### Config File (`occ.yml`)

```yaml
# Model configuration
model: "claude-sonnet-4-20250514"
# model: "openrouter/anthropic/claude-sonnet-4"  # needs OPENROUTER_API_KEY
max_tokens: 16000
max_tool_output: 10000

# OpenAI-compatible endpoint (Together, vLLM, …). Not needed for OpenRouter.
# base_url: "https://api.together.xyz/v1"

# Mode: ask | plan | agent
mode: "agent"

# Safety
skip_approval: false          # true = auto-approve ALL tool calls (dangerous!)
permission_mode: "workspace-write"  # read-only | workspace-write | full-access
disallowed_tools: []          # Names/patterns blocked even when approvals are skipped
workspace_roots: ["."]        # Readable roots for filesystem tools
writable_roots: ["."]         # Writable roots for edit/write tools
shell_policy: "workspace-write"  # read-only | workspace-write | full-access
auto_approve:                 # Tools that skip the approval prompt
  - read_file
  - list_directory
  - find_files
  - grep_search
  - web_search
  - read_url
  - load_skill
  - git_status
  - git_diff
  - git_log
  - git_branch
  - wait_agent

# Prompt caching (Anthropic only — up to 90% cost reduction)
prompt_caching: true

# Cost. Prices are USD per million tokens. Unknown models print
# "price unknown" instead of $0.00. Ollama is treated as free.
# max_budget_usd: 5.0
# model_prices:
#   my-local-model:
#     input: 0.0
#     output: 0.0

# Context management
max_context_tokens: 100000
context_compaction: true

# Durable local session transcripts
persist_sessions: true
sessions_dir: ".occ/sessions"
persist_snapshots: true
snapshots_dir: ".occ/snapshots"

# Public web access and cache
network_enabled: true
web_allowed_domains: []
web_blocked_domains: []
web_cache_dir: ".occ/cache/web"
web_max_response_bytes: 1000000

# Provider retries and reusable subagent definitions
provider_max_retries: 2
max_turns: 100
agents_dirs:
  - ".occ/agents"
personas_dirs:
  - ".occ/personas"
  - "~/.occ/personas"

# Extension directories
skills_dirs:
  - "~/.occ/skills"
  - ".occ/skills"

plugins_dirs:
  - "~/.occ/plugins"
  - ".occ/plugins"

# MCP servers
mcp_servers:
  - name: filesystem
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

> A fully annotated example is included in [`occ.example.yml`](occ.example.yml).

### CLI Flags

```bash
occ --model gpt-4o           # Override model
occ --mode plan               # Start in plan mode
occ --max-tokens 32000        # Increase response length
occ --skip-approval            # Auto-approve all tools (caution!)
occ --api-key sk-...           # Pass API key directly
occ --base-url https://...    # Custom endpoint
occ --config ./my-config.yml  # Custom config path
occ --resume 20260712T...     # Resume a durable local session
occ --max-budget 5            # Stop when known session cost reaches $5
occ doctor                    # Keys, provider mapping, Ollama, ripgrep
occ doctor --json             # Same report as JSON for CI
occ doctor --report out.json  # Persist the JSON report
```

---

## 💬 Slash Commands

Inside the interactive REPL:

| Command | Description |
|---------|-------------|
| `/ask <query>` | Force ask mode for one turn (no tools) |
| `/plan <task>` | Force plan mode for one turn (plan → approve → execute) |
| `/agent <task>` | Force agent mode for one turn (full autonomy) |
| `/mode [ask\|plan\|agent]` | Show or switch the default interaction mode |
| `/skill [list\|load\|unload\|reload]` | Manage prompt-based skills |
| `/plugin [list\|reload]` | Manage Python lifecycle plugins |
| `/mcp [list\|add\|remove]` | Manage MCP servers at runtime |
| `/plan [show\|progress\|clear]` | Manage the current plan/checklist |
| `/memory` | List loaded memory files (`AGENTS.md`, `CLAUDE.md`, etc.) |
| `/memory reload` | Rescan and reload memory files |
| `/memory show` | Preview loaded memory content |
| `/status` | Show model, permissions, context, and session details |
| `/cost` | Show token usage, USD (or `price unknown`), API duration, and lines changed |
| `/sessions` | List durable local sessions |
| `/changes` | Show current Git status and uncommitted diff |
| `/undo <file>` | Restore the latest OCC file snapshot |
| `/rename <title>` | Give the active session a human-readable title |
| `/export <path>` | Write a reproducible JSON task capsule |
| `/agent list` | List built-in roles (`explore`, `plan`, `general-purpose`) and `.occ/agents` / `.occ/personas` |
| `/clear` | Clear conversation history |
| `/help` | Show command reference |

---

## 🧪 Development

Setup, tests, PR shape, and safety rules for contributors are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Setup

```bash
git clone https://github.com/NastyRunner13/Open-Claude-Code.git
cd Open-Claude-Code
uv sync              # Install all dependencies including dev
```

### Run Tests

```bash
uv run pytest tests/ -v
```

The test suite includes **200+ tests** covering:
- Agent loop and tool dispatch
- Configuration loading and cascading
- Event bus routing and listeners
- Context compaction and token estimation
- Mode routing (ask, plan, agent)
- Middleware lifecycle and composition
- Memory file discovery and caching
- Planning tools and checklist management
- Provider registry and auto-detection
- Individual tool implementations
- Structured ToolResult handling

### Run Locally

```bash
uv run occ
```

### Build for Distribution

```bash
uv build    # Produces .whl and .tar.gz in dist/
```

### Docker

```bash
docker build -t occ .
docker run -it -e ANTHROPIC_API_KEY=sk-ant-... occ
```

---

## 🗺 Roadmap

Here are features and improvements planned for future releases:

- [ ] **Git integration** — automatic staging, committing, branching, and PR creation
- [x] **File snapshots, diffs & undo** — snapshots and unified diffs for write/edit/patch operations
- [x] **Streaming responses** — token-by-token streaming across providers
- [ ] **IDE integration** — VS Code extension and Language Server Protocol support
- [ ] **Persistent memory** — learn project conventions, build commands, and preferences across sessions
- [x] **Hooks system** — trusted `occ.yml` command hooks (pre/post tool, stop)
- [x] **Session export** — export conversation history to a JSON task capsule (`/export`)
- [x] **Multi-agent orchestration** — built-in explore/plan/GP children, background wait, worktrees, resume, steer, and `run_workflow` phase barriers
- [x] **Diff-based editing** — `apply_patch` applies unified diffs atomically
- [x] **Cost tracking** — `/cost` from real usage, price table, `max_budget_usd`, `occ doctor`

See the [improvement analysis](https://github.com/NastyRunner13/Open-Claude-Code/blob/main/IMPROVEMENTS.md) for a detailed comparison with Claude Code and other agents.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<div align="center">
  <p><strong>Built with ❤️ by <a href="https://github.com/NastyRunner13">Prince Gupta</a></strong></p>
  <p>
    <a href="https://github.com/NastyRunner13/Open-Claude-Code/stargazers">⭐ Star this repo</a> ·
    <a href="https://github.com/NastyRunner13/Open-Claude-Code/issues">🐛 Report a bug</a> ·
    <a href="https://github.com/NastyRunner13/Open-Claude-Code/issues">💡 Request a feature</a>
  </p>
</div>
