# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Sub-agent runtime: built-in `explore` / `plan` / `general-purpose` roles, background spawn + `wait_agent`, `kill_agent`, `send_agent_message` (steer/queue), `resume_from`, `isolation=worktree` with `apply_agent_worktree`, personas from `.occ/personas`, and `run_workflow` phase barriers. Children get their own planning store. Nested spawn stays denied.
- First-class OpenRouter provider: `openrouter/<vendor>/<model>` (and `vendor/model` when `OPENROUTER_API_KEY` is set). Sends OpenRouter attribution headers. Missing key raises `ProviderError`.
- YAML `base_url` is parsed so OpenAI-compatible endpoints can live in `occ.yml`.

### Fixed

- `/plan <task>` and `/agent <task>` now run one-shot plan/agent mode. `/agent list` still lists roles; `/plan show|clear|progress` still manage the checklist.
- `occ exec` is non-interactive by default: privileged tools are denied unless `--approval-mode auto` or `full-access` is set. Missing task exits 2. `--quiet` suppresses non-final JSON progress.
- Child agents cannot raise `permission_mode` above the parent. Spawn approval shows `task` and `permission_mode`.
- Gemini tool follow-up uses the function declaration name, not `tool_use_id`.
- Anthropic extended thinking is opt-in for known thinking models, not every `claude*` name.
- Provider streams attach token usage on `done`.
- MCP server `env` is merged with the process environment (so `PATH` survives `npx`). Stderr is drained. JSON-RPC `error` and `isError` become `ToolResult.fail`.
- `workspace-write` denies unknown shell commands, not only a few destructive regexes. Timeouts kill the process group.
- Unbound filesystem/shell/web tools fail closed instead of skipping policy.
- Streaming UI no longer reprints the answer in a panel after live tokens. `AgentStart` starts the thinking spinner.
- OpenAI-compatible hosts that reject `max_completion_tokens` are retried with `max_tokens` (remembered for the rest of the session).
- Stream `include_usage` is dropped and retried when the host 400s on `stream_options`.
- Groq/compat models that reject tools raise a clear `ProviderError` instead of a generic OpenAI exception.
- OpenAI-compat stream 429/5xx errors are marked transient so the agent retry loop can fire.

### Changed

- Groq routing requires the `groq/` prefix. Unprefixed `llama-*` / `mixtral-*` / `gemma-*` / `deepseek-*` are no longer stolen when `GROQ_API_KEY` is set.
- `sandbox` schema no longer claims filesystem or network isolation.
- Built-in tool count documented as 25 (including git, patch, multi-edit, undo, and sub-agent coordination).
- Default `auto_approve` includes read-only git tools and `load_skill`.

## [0.1.0] — 2026-03-28

### Added

- Multi-model support: Anthropic, OpenAI, Google Gemini, Groq, Ollama, and any OpenAI-compatible endpoint.
- Three interaction modes: `ask`, `plan`, and `agent`.
- 20 built-in tools: `read_file`, `write_file`, `edit_file`, `multi_edit`, `apply_patch`, `undo_edit`, `list_directory`, `find_files`, `grep_search`, `run_shell`, `web_search`, `read_url`, `sandbox`, `spawn_agent`, `load_skill`, `git_status`, `git_diff`, `git_log`, `git_branch`.
- Extensible skills system (Markdown+YAML prompt files).
- Python plugin system with lifecycle hooks.
- Model Context Protocol (MCP) integration for external tool servers.
- Smart context management with automatic compaction and summarization.
- Interactive REPL with `prompt_toolkit` (command history, auto-complete).
- Rich terminal UI with colored splash screen and spinners.
- YAML+env+CLI cascading configuration system.
- Memory middleware for `AGENTS.md` / `CLAUDE.md` context files.
- Planning middleware with checklist tracking.
- Sub-agent spawning for parallel task execution.
- Comprehensive test suite (12 test modules).
