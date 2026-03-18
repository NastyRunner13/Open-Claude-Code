# Open Claude Code (OCC)

An open-source AI coding agent that runs in your terminal. Works with **any LLM** — Claude, GPT, Gemini, Groq, Ollama, or any OpenAI-compatible endpoint.

## ⚡ Quick Start

```bash
# Install
pip install open-claude-code
# or with uv
uv sync

# Run (requires ANTHROPIC_API_KEY by default)
occ

# Use different models
occ --model gpt-4o                          # OpenAI
occ --model gemini-2.0-flash                # Google Gemini
occ --model groq/llama-3.3-70b-versatile    # Groq
occ --model ollama/llama3.2                 # Local Ollama
occ --model my-model --base-url https://custom-api.com/v1  # Any endpoint
```

## 🎯 Features

### 12 Built-in Tools
| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Create/overwrite files |
| `edit_file` | Surgical string replacement |
| `list_directory` | List directory contents |
| `find_files` | Glob pattern file search |
| `grep_search` | Ripgrep-powered code search |
| `run_shell` | Execute shell commands |
| `web_search` | DuckDuckGo web search |
| `read_url` | Fetch and parse URLs |
| `sandbox` | Isolated Python execution |
| `spawn_agent` | Parallel sub-agents |
| `load_skill` | Load skills at runtime |

### 3 Interaction Modes

| Mode | Prompt | Behavior |
|------|--------|----------|
| **Ask** | `?` | No tools — direct Q&A |
| **Plan** | `📋` | Plan → review → execute |
| **Agent** | `❯` | Full autonomous mode |

### 5 LLM Providers
Anthropic · OpenAI · Google Gemini · Groq · Ollama — plus any OpenAI-compatible API via `--base-url`.

### Skills System
Extend agent capabilities with SKILL.md files:
```
.occ/skills/my-skill/SKILL.md
```
```yaml
---
name: My Skill
description: What it does
---
Instructions for the LLM when this skill is loaded...
```

### Plugin System
Python plugins with lifecycle hooks (`on_agent_start`, `on_before_send`, `on_after_response`, `on_tool_result`, `on_agent_stop`):
```python
# .occ/plugins/my-plugin/plugin.py
PLUGIN_NAME = "My Plugin"

def register(hooks):
    async def on_start(**kwargs):
        print("Agent started!")
    hooks.on_agent_start(on_start)
```

### MCP Integration
Connect to Model Context Protocol servers:
```yaml
# occ.yml
mcp_servers:
  - name: filesystem
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

### Context Management
Automatic conversation compaction to stay within context limits — keeps first + recent messages, summarizes the middle.

## 🔧 Configuration

Configuration sources (in priority order): CLI flags → env vars → `occ.yml` → defaults.

```bash
# CLI flags
occ --model gpt-4o --mode plan --api-key sk-... --base-url https://...

# Environment variables
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export GROQ_API_KEY=gsk_...
export GEMINI_API_KEY=...
```

See `occ.example.yml` for full config reference.

## 💬 Slash Commands

| Command | Description |
|---------|-------------|
| `/ask <question>` | Quick answer (no tools) |
| `/plan <task>` | Plan → approve → execute |
| `/agent <task>` | Full agent mode |
| `/mode [ask\|plan\|agent]` | Show/switch mode |
| `/skill list` | List available skills |
| `/skill load <name>` | Load a skill |
| `/clear` | Clear conversation |
| `/help` | Show all commands |

## 🏗 Architecture

```
open_claude_code/
├── agent.py          # Core agent loop
├── config.py         # YAML + env + CLI config
├── context.py        # Conversation compaction
├── events.py         # Event bus system
├── listeners.py      # UI, approval, logging
├── main.py           # CLI entry point + REPL
├── modes.py          # Ask/Plan/Agent mode router
├── system_prompt.py  # Mode-specific prompts
├── mcp/              # MCP client + bridge
├── plugins/          # Plugin lifecycle hooks
├── providers/        # LLM providers (5+)
├── skills/           # Skill loader + manager
├── subagents/        # Sub-agent manager
└── tools/            # 12 built-in tools
```

## 📦 Development

```bash
# Clone and setup
git clone <repo>
cd OpenClaudeCode
uv sync

# Run tests
uv run pytest tests/ -v

# Run the agent
uv run occ
```

## License

MIT
