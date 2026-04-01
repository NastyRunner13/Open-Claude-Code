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

- 🧠 **Bring any model** — switch from Claude to GPT-4o to a local Llama with a single flag
- 🛠️ **12 built-in tools** — file I/O, code search, shell execution, web search, sandboxed Python, and more
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

# Groq (blazing fast inference)
occ --model groq/llama-3.3-70b-versatile

# Local models via Ollama
occ --model ollama/llama3.2

# Any OpenAI-compatible endpoint (OpenRouter, Together, vLLM, etc.)
occ --model my-model --base-url https://api.openrouter.ai/v1
```

### Provider detection logic

| Model prefix | Provider | API Key env var |
|---|---|---|
| `claude-*` | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI | `OPENAI_API_KEY` |
| `gemini-*` | Google Gemini | `GEMINI_API_KEY` |
| `groq/*` | Groq | `GROQ_API_KEY` |
| `ollama/*` | Ollama (local) | — |
| `--base-url` flag | OpenAI-compatible | `OPENAI_API_KEY` |

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
| `list_directory` | List directory contents with metadata | ✅ |
| `find_files` | Glob-based file search | ✅ |
| `grep_search` | Ripgrep-powered code search with context lines | ✅ |
| `run_shell` | Execute shell commands with output capture | ❌ |
| `web_search` | Search the web via DuckDuckGo | ✅ |
| `read_url` | Fetch and parse web pages to markdown | ✅ |
| `sandbox` | Execute Python code in an isolated subprocess | ❌ |
| `spawn_agent` | Spawn parallel sub-agents for concurrent tasks | ❌ |
| `load_skill` | Dynamically load skills to extend prompts | ✅ |

> **Auto-approved** tools run without prompting you. Configure this in `occ.yml` via `auto_approve`.

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

Connect external tool servers that speak the [Model Context Protocol](https://modelcontextprotocol.io/) standard:

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
│   └── ollama.py         # Local models via Ollama
│
├── tools/                # Tool definitions (schema + implementation)
│   ├── read_file.py      # File reading with line limits
│   ├── write_file.py     # File creation with parent dir auto-creation
│   ├── edit_file.py      # Surgical search-and-replace editing
│   ├── grep_search.py    # Ripgrep-powered code search
│   ├── find_files.py     # Glob-based file finding
│   ├── list_directory.py # Directory listing with metadata
│   ├── run_shell.py      # Shell command execution
│   ├── web_search.py     # DuckDuckGo web search
│   ├── read_url.py       # URL fetching + HTML→markdown conversion
│   ├── sandbox.py        # Isolated Python execution
│   ├── spawn_agent.py    # Sub-agent spawning for parallelism
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
├── subagents/            # Sub-agent spawning and management
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
export OCC_MODEL="gpt-4o"    # Override default model
```

### Config File (`occ.yml`)

```yaml
# Model configuration
model: "claude-sonnet-4-20250514"
max_tokens: 16000

# Mode: ask | plan | agent
mode: "agent"

# Safety
skip_approval: false          # true = auto-approve ALL tool calls (dangerous!)
auto_approve:                 # Tools that skip the approval prompt
  - read_file
  - list_directory
  - find_files
  - grep_search
  - web_search
  - read_url
  - load_skill

# Prompt caching (Anthropic only — up to 90% cost reduction)
prompt_caching: true

# Context management
max_context_tokens: 100000
context_compaction: true

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
| `/mcp [list\|add\|remove]` | Manage MCP servers at runtime |
| `/plan [show\|progress\|clear]` | Manage the current plan/checklist |
| `/memory` | List loaded memory files (`AGENTS.md`, `CLAUDE.md`, etc.) |
| `/memory reload` | Rescan and reload memory files |
| `/memory show` | Preview loaded memory content |
| `/clear` | Clear conversation history |
| `/help` | Show command reference |

---

## 🧪 Development

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
- [ ] **File snapshots & undo** — snapshot files before edits for easy rollback
- [ ] **Streaming responses** — token-by-token streaming for faster feedback
- [ ] **IDE integration** — VS Code extension and Language Server Protocol support
- [ ] **Persistent memory** — learn project conventions, build commands, and preferences across sessions
- [ ] **Hooks system** — pre/post shell hooks for custom automation (linting, formatting, etc.)
- [ ] **Session export** — export conversation history to Markdown or JSON
- [ ] **Multi-agent orchestration** — coordinate multiple agents on different parts of a codebase
- [ ] **Diff-based editing** — apply unified diffs instead of string replacement for complex edits
- [ ] **Cost tracking** — real-time token usage and spending dashboard

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
