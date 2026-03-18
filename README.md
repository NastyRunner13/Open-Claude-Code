# Open Claude Code (OCC)

An open-source, terminal-based AI coding agent inspired by Claude Code.

## Features

- **Coding-first agent** — reads, writes, edits, and searches your codebase
- **11 built-in tools** — file I/O, shell, web search, code sandbox, grep, sub-agents
- **Multiple modes** — Ask (quick questions), Plan (review before executing), Agent (full auto)
- **Extended thinking** — see the model's reasoning process
- **Event-driven architecture** — clean, extensible design with zero side-effects in the core loop
- **Beautiful Rich UI** — styled tool calls, thinking traces, and markdown responses
- **Configurable** — YAML config + env vars + CLI flags

## Quick Start

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key

### Install

```bash
# Clone the repo
git clone <your-repo-url>
cd OpenClaudeCode

# Install dependencies
uv sync

# Set your API key
export ANTHROPIC_API_KEY=your-key-here    # Linux/Mac
set ANTHROPIC_API_KEY=your-key-here       # Windows
```

### Run

```bash
uv run occ
```

### Slash Commands

| Command | Description |
|---------|-------------|
| `/ask <question>` | Quick answer, no tools |
| `/plan <task>` | Create a plan before executing |
| `/agent <task>` | Full agent mode (default) |
| `/mode` | Show current mode |
| `/mode <ask\|plan\|agent>` | Switch default mode |
| `/clear` | Clear conversation history |
| `/help` | Show help |

## Configuration

Create `occ.yml` in your project directory:

```yaml
model: claude-sonnet-4-20250514
max_tokens: 16000
mode: agent
skip_approval: false
auto_approve:
  - read_file
  - list_directory
  - find_files
  - grep_search
  - web_search
  - read_url
```

## Architecture

OCC follows an event-driven agent loop pattern:

```
User Input → Provider (LLM) → Tool Use? → Execute Tools → Loop
                                    ↓ No
                              Final Response
```

The agent loop emits lifecycle events. All side effects (UI, approval, logging) are handled by event listeners, keeping the core loop clean.

## Tools

| Tool | Category | Description |
|------|----------|-------------|
| `read_file` | Files | Read file contents |
| `write_file` | Files | Create/overwrite files |
| `edit_file` | Files | Surgical string replacement |
| `list_directory` | Navigation | List dir contents |
| `find_files` | Navigation | Glob-based file search |
| `grep_search` | Navigation | Regex search with ripgrep |
| `run_shell` | System | Execute shell commands |
| `sandbox` | System | Isolated code execution |
| `web_search` | Network | DuckDuckGo web search |
| `read_url` | Network | Fetch URL content |
| `spawn_agent` | Agents | Spawn parallel sub-agents |

## License

MIT
