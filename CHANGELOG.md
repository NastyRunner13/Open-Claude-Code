# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-03-28

### Added

- Multi-model support: Anthropic, OpenAI, Google Gemini, Groq, Ollama, and any OpenAI-compatible endpoint.
- Three interaction modes: `ask`, `plan`, and `agent`.
- 12 built-in tools: `read_file`, `write_file`, `edit_file`, `list_directory`, `find_files`, `grep_search`, `run_shell`, `web_search`, `read_url`, `sandbox`, `spawn_agent`, `load_skill`.
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
