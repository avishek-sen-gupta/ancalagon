## Project Context

- **Language:** Python 3.13+ (main codebase), Markdown (docs)
- **Package manager:** uv (`uv run` prefix for all commands)
- **Test framework:** pytest
- **Formatter:** Black
- **Specs (immutable):** `docs/superpowers/specs/` and `docs/superpowers/plans/` — never modify these. Newer specs supersede older ones by convention.

## What This Is

An agent harness for reverse engineering. Given a data structure and a goal, an agent either works it directly with tools, or generates a deterministic traversal program plus Pydantic contracts for its own analysis touch points, and runs that under supervision.

Related project: `~/code/red-dragon` (RedDragon) — IR, CFG, and dataflow for multi-language program analysis. Ancalagon consumes artifacts of that kind, but does not depend on it.

## External Dependencies

- LiteLLM for model access (provider-agnostic, behind a local `LLM` protocol).
- `ripgrep`, `ast-grep`, `sed` on PATH.
- tree-sitter grammars for languages under analysis.
- SQLite (stdlib) for the task bus.
