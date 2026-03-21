<div align="center">
  <h1>⚡ Open Claude Code (OCC)</h1>
  <p>An open-source, extensible AI coding agent that runs right in your terminal. Works with <b>any LLM</b> — Claude, GPT, Gemini, Groq, Ollama, or any OpenAI-compatible endpoint.</p>
</div>

---

## ✨ Key Features

- **Multi-Model Support**: Native support for Anthropic, OpenAI, Google Gemini, Groq, and Ollama. Seamlessly switch models or use any OpenAI-compatible custom endpoint.
- **3 Interaction Modes**: Choose how much autonomy you want. From simple Q&A (`ask`), to review-driven execution (`plan`), to full autonomous tool usage (`agent`).
- **12 Built-in Tools**: Read/write files, edit surgically, list directories, search via glob or Ripgrep, execute shell commands, perform isolated Python execution, web searches, fetch URLs, and even spawn sub-agents.
- **Extensible Architecture**: 
  - **Skills**: Add new prompt-based capabilities at runtime via simple Markdown+YAML files.
  - **Plugins**: Write Python plugins that hook into the agent's lifecycle (`on_agent_start`, `on_before_send`, etc.).
- **Model Context Protocol (MCP)**: Directly connect to specialized external tool servers (e.g., GitHub, Filesystem, SQLite) via MCP.
- **Smart Context Management**: Keeps conversation context within token limits automatically by retaining the most important messages and summarizing the rest.

---

## 🚀 Installation & Quick Start

You can install Open Claude Code globally via pip or use it directly with `uv`. Python 3.12+ is required.

```bash
# Install package
pip install open-claude-code

# Alternatively, run using uv (recommended for dev)
uv sync

# Run out of the box (Defaults to Anthropic; requires ANTHROPIC_API_KEY)
occ
```

### Try different models instantly:

```bash
occ --model gpt-4o                          # OpenAI
occ --model gemini-2.0-flash                # Google Gemini
occ --model groq/llama-3.3-70b-versatile    # Groq
occ --model ollama/llama3.2                 # Local Ollama
occ --model my-model --base-url https://custom-api.com/v1  # Any endpoint
```

---

## 🛠️ Interaction Modes

Open Claude Code respects your workflow by providing three distinct interaction modes:

| Mode | Symbol | Description | Behavior |
|------|:---:|-------------|----------|
| **Ask** | `?` | Direct Q&A | The agent answers your programming questions without using any tools. Fast and cheap. |
| **Plan** | `📋` | Plan & Review | The agent creates a step-by-step checklist of actions, asks for your review, and executes them one by one. |
| **Agent** | `❯` | Autonomous | Full agentic mode. The agent iteratively uses tools, assesses results, and solves complex tasks until complete. |

*Switch modes on the fly inside the CLI using `/mode [ask|plan|agent]`.*

---

## 🧰 Built-in Tools

The agent is equipped with a robust set of tools to interact with your local environment:

| Tool | Core Functionality |
|------|--------------------|
| `read_file` | Read up to a specific number of lines from a file. |
| `write_file` | Create new files or overwrite existing ones. |
| `edit_file` | Make surgical string replacements in existing files. |
| `list_directory` | Explore directories and list their contents. |
| `find_files` | Search for files by glob pattern. |
| `grep_search` | Ripgrep-powered lightning-fast code search. |
| `run_shell` | Execute arbitrary shell commands (safely prompted). |
| `web_search` | Search the web natively using DuckDuckGo. |
| `read_url` | Fetch and parse web pages to markdown context. |
| `sandbox` | Execute Python snippets in an isolated environment. |
| `spawn_agent` | Spin up parallel sub-agents for concurrent tasks. |
| `load_skill` | Dynamically import skills to expand prompt instructions. |

---

## 🔌 Extensibility (Skills, Plugins, & MCP)

### 1. Skills (Prompt Engineering)
You can teach the agent new workflows by dropping a `SKILL.md` file into `.occ/skills/my-skill/`.
```yaml
---
name: GitHub PR Review
description: Best practices for reviewing PRs
---
When asked to review a PR, always check for test coverage and proper typing...
```
*Load it by typing `/skill load GitHub PR Review` in the CLI.*

### 2. Plugins (Python Lifecycle Hooks)
Need programmatic extension? Write standard Python plugins. Place them in `.occ/plugins/my-plugin/plugin.py`:
```python
PLUGIN_NAME = "Custom Logger"

def register(hooks):
    async def log_tool(tool_name, **kwargs):
        print(f"Agent just used: {tool_name}")
    hooks.on_tool_result(log_tool)
```

### 3. Model Context Protocol (MCP)
Extend the agent with external standardized tools (e.g., database clients, specialized APIs). Add to your `occ.yml`:
```yaml
mcp_servers:
  - name: filesystem
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

---

## ⚙️ Configuration 

`occ` uses a cascading configuration system. Order of priority: 
**CLI Flags** → **Environment Variables** → **`occ.yml` / `.occ/config.yml`**

**Environment Variables:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
export GROQ_API_KEY="gsk_..."
```

**Example `occ.yml` Configuration:**
```yaml
model: "claude-3-7-sonnet-20250219"
max_tokens: 16000
mode: "agent"
skip_approval: false   # Set to true for fully unattended runs
auto_approve:
  - read_file
  - list_directory
  - grep_search
```

---

## 💬 Slash Commands

Inside the interactive REPL, use these slash commands to control the agent:

| Command | Description |
|---------|-------------|
| `/ask <query>` | Quick answer (forces `ask` mode for one turn) |
| `/plan <task>` | Plan & Execute (forces `plan` mode for one turn) |
| `/agent <task>` | Full Autonomous (forces `agent` mode for one turn) |
| `/mode [ask\|plan\|agent]` | Show current mode or switch default mode |
| `/skill` | Manage skills (`list`, `load <name>`, `unload <name>`) |
| `/mcp` | Manage MCP servers (`list`, `add`, `remove`) |
| `/plan [cmd]` | Manage current checklist (`show`, `progress`, `clear`) |
| `/memory` | Manage context files (`/memory reload`, `/memory show`) |
| `/clear` | Clear conversation history and context window |
| `/help` | Display the help menu |

---

## 🏗 Architecture Focus

The codebase is highly modular and organized in `src/open_claude_code/`:
- **`agent.py`**: The core autonomous loop.
- **`middleware/`**: Modular systems (MCP, Memory, Skills) evaluated in sequence.
- **`tools/`**: Tool definitions and payload schemas.
- **`providers/`**: LLM-agnostic provider wrappers.
- **`context.py`**: Smart conversation token tracking and compactor logic.
- **`modes.py` & `system_prompt.py`**: Mode routing strings and persona definitions.

---

## 📦 Local Development & Contributing

Contributions are highly welcome! To set up the project locally:

1. **Clone & Install**
   ```bash
   git clone https://github.com/your-username/OpenClaudeCode.git
   cd OpenClaudeCode
   uv sync
   ```

2. **Run Tests**
   ```bash
   uv run pytest tests/ -v
   ```

3. **Run the CLI locally**
   ```bash
   uv run occ
   ```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
