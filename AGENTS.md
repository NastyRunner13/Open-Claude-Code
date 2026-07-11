# Coding-agent guide for Open Claude Code

## Project map

- `src/open_claude_code/agent.py` owns the provider/tool loop, authorization,
  streaming-event consumption, and session recording. Keep it UI-independent.
- `src/open_claude_code/main.py` owns CLI parsing, terminal behavior,
  middleware construction, and non-interactive `occ exec` behavior.
- `src/open_claude_code/tools/` contains built-in tool schemas and their
  implementations. Runtime tools are bound in `tools/__init__.py`.
- `src/open_claude_code/middleware/` owns optional capabilities and lifecycle
  integration; preserve the ordering in `main.py` unless a change requires it.
- `src/open_claude_code/providers/` normalizes provider responses and streams.
- `src/open_claude_code/sessions/`, `subagents/`, `skills/`, and `mcp/` own
  their corresponding persistent or extension boundaries.
- `tests/` mirrors these areas. Add regression tests beside the closest
  existing test module.

## Working rules

1. Preserve the security boundary. Built-in filesystem, shell, and web tools
   must receive and honor `ToolContext`; do not bypass it by calling raw paths,
   subprocesses, or HTTP clients from a tool implementation.
2. Enforce capabilities before approval. `ToolPolicy` and tool-local checks are
   non-bypassable; approval prompts only decide among policy-permitted calls.
3. Keep provider-specific code in `providers/`. The agent loop should consume
   normalized `ProviderResponse` and stream events only.
4. Return `ToolResult` from tools, including failures, with useful metadata.
   Preserve output truncation and report denied operations through `ToolDenied`.
5. Make edits reversible. Write, edit, multi-edit, and patch changes should use
   snapshots and return a unified diff when applicable.
6. Treat sessions as an append-only audit trail. Do not write credentials to
   session metadata or events; use the existing redaction path.
7. Keep compatibility with Python 3.12+, use type annotations, and avoid new
   runtime dependencies unless the feature needs them.

## Verification

Use the project environment and run focused tests while iterating:

```powershell
uv run pytest tests/test_tools.py
uv run pytest tests/test_agent.py
```

Before handing off a meaningful change, run the full suite:

```powershell
uv run pytest
```

For CLI changes, also check the help surface:

```powershell
uv run occ --help
```

## Documentation and repository hygiene

- Keep `README.md`, `occ.example.yml`, and `IMPROVEMENTS.md` accurate when
  behavior or configuration changes.
- Mark roadmap work as implemented only after it is wired into the normal CLI
  path and protected by regression coverage.
- Do not modify generated/runtime directories such as `.occ/`, `.venv/`,
  `.pytest_cache/`, `pytest_temp/`, or `dist/` unless the task explicitly asks
  for them.
- Preserve user changes already present in the working tree and avoid
  destructive Git operations.
