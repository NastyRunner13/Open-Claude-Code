# Contributing to Open Claude Code

Thanks for wanting to work on OCC. This file is the human path: how to set up a checkout, what a good change looks like, and how we review it. Agent-oriented layout and invariants live in [`AGENTS.md`](AGENTS.md). The work order lives in [`IMPROVEMENTS.md`](IMPROVEMENTS.md).

## Setup

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are the supported toolchain.

```bash
git clone https://github.com/NastyRunner13/Open-Claude-Code.git
cd Open-Claude-Code
uv sync --all-extras --dev
uv run occ --help
```

Run the agent from the checkout with `uv run occ`. Put API keys in the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and so on). Do not commit keys, session transcripts, or `.occ/` artifacts.

## Tests

CI runs `uv run pytest tests/ -v --tb=short` on Python 3.12 and 3.13, then `uv build`.

While iterating, run the closest module:

```bash
uv run pytest tests/test_tools.py
uv run pytest tests/test_agent.py
```

Before you open a PR, run the suite:

```bash
uv run pytest tests/
```

For CLI changes, also check the help surface and exec usage errors:

```bash
uv run occ --help
uv run occ exec
```

`occ exec` with no task must exit 2. Do not run `pytest` from the repo root without `tests/`; local `pytest_temp/` directories can break collection on Windows.

New behavior needs a regression test on the path a user actually hits. Slash commands should test `handle_slash_command`. Exec flags should test argv parsing and approval wiring. Tool policy should test the bypass string, not only the happy path.

## What belongs where

| Area | Path |
| --- | --- |
| Agent loop | `src/open_claude_code/agent.py` |
| CLI, REPL, `occ exec` | `src/open_claude_code/main.py` |
| Built-in tools | `src/open_claude_code/tools/` |
| Provider SDKs | `src/open_claude_code/providers/` |
| Middleware | `src/open_claude_code/middleware/` |
| Tests | `tests/`, next to the closest existing module |

Keep the agent loop free of UI and approval prompts. Providers return `ProviderResponse` and stream events. Tools return `ToolResult` and honor `ToolContext`. Do not call raw paths, subprocesses, or HTTP clients from a tool to skip policy.

## Safety rules we will not waive

- `ToolPolicy` and tool-local checks run before any approval prompt. `skip_approval` cannot grant a denied capability.
- Child agents cannot raise `permission_mode` above the parent.
- `occ exec` is non-interactive by default. Privileged tools stay denied unless `--approval-mode auto` or `full-access` is explicit.
- Sessions are an append-only ledger. Do not write credentials into session metadata or events.
- File edits should snapshot and return a unified diff when the tool already does that.

If a change weakens one of these, say so in the PR. Silent relaxations get rejected.

## Code style

- Python 3.12+, type annotations on new code.
- No new runtime dependency unless the feature cannot ship without it. Optional extras (Gemini) stay optional.
- Prefer inline logic. Extract a helper when the same block appears in more than one place, or when a name is the policy (`clamp_permission_mode`, `unbound_result`).
- Match the surrounding file. Do not reformat unrelated code.

## Docs

Behavior or config changes need the matching docs in the same PR:

- [`README.md`](README.md) for user-facing flags, tools, and slash commands
- [`occ.example.yml`](occ.example.yml) for config keys
- [`CHANGELOG.md`](CHANGELOG.md) under `[Unreleased]`
- [`IMPROVEMENTS.md`](IMPROVEMENTS.md) only after the change is on the CLI path and covered by a test

Do not mark a roadmap item implemented from a README checkbox.

## Pull requests

1. Pick an item from `IMPROVEMENTS.md` in file order. Wave 1 is done. Do not start Wave 4 work while Wave 2/3 gaps are open unless you are fixing a user-visible break.
2. One concern per PR. A slash-command fix and an OpenRouter provider do not belong together.
3. Describe what a user can do now that they could not before, or what stopped being a lie.
4. Include tests. Include doc updates when the public surface moved.

Commit messages follow the existing style:

```
fix(cli): deny privileged tools in occ exec by default

Exec registered an interactive Y/n prompt, which hangs CI.
Missing task now exits 2. --quiet keeps only the final JSON event.
```

Use `fix`, `feat`, `docs`, `test`, or `chore`. Put the area in parentheses when it helps (`cli`, `tools`, `providers`, `mcp`, `subagents`).

## Out of scope unless a task asks for it

Leave `.occ/`, `.venv/`, `.pytest_cache/`, `pytest_temp/`, and `dist/` alone. Do not add another provider SDK when OpenRouter or `--base-url` would cover it. Do not add a VS Code extension on top of an exec path that prompts Y/n.

## License

By contributing you agree that your work is released under the MIT License in [`LICENSE`](LICENSE).
