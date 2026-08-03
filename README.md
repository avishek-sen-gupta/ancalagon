# Ancalagon

An agent harness for reverse engineering.

## What it does

Give it a goal. An agent pursues it with tools — ripgrep, ast-grep, tree-sitter,
stream-only sed, scoped file access — and delegates focused subtasks to isolated
subagent processes, each with its own budget and its own typed output contract.

A goal is all it needs. Point `read_roots` at whatever the agent should be able to
read — a repository, a directory of parsed artifacts, a single JSON file, or nothing
at all — and it stays inside that boundary.

Subagents return typed results. A parent can write a Pydantic model at runtime and
require its children to answer in that shape, so a fan-out produces structured data
rather than prose.

## Running

```bash
uv sync
cp ancalagon.example.toml ancalagon.toml   # edit write_root and read_roots
uv run ancalagon run --config ancalagon.toml --goal "..."
```

Watch a run as it happens, including subagents spawned mid-run:

```bash
./scripts/ancwatch.zsh ws          # start before or during a run
```

On Bedrock with a bearer token, `scripts/ancrun.zsh` runs the same command with
stale AWS credentials stripped from the environment — otherwise litellm signs with
those instead and Bedrock rejects the request.

## How it works

Three kinds of process, communicating only through SQLite rows and files:

- **Root agent** — reasons, uses tools, delegates.
- **Supervisor** — spawns, reaps, kills on timeout. Never retries; a crash is
  reported and the parent decides. The only module that constructs `Popen`.
- **Worker** — one agent session per process, one attempt at one task.

There is no IPC. A parent writes `spec.json` and enqueues a row; a worker writes
`outcome.json` and `transcript.jsonl`. A subagent that needs input returns
`NeedsInput` and stops rather than asking mid-run, so nothing blocks and a dead
child cannot hang its parent.

## Inspecting a run

Everything is on disk and in one SQLite file:

```bash
sqlite3 ws/runs/r_0001/bus.db "select id, dir, status, exit_code, summary from tasks"
rg '"agent": 17' ws/runs/r_0001/tasks/*/transcript.jsonl
```

Transcripts are appended and flushed per message, so a killed agent leaves a
readable partial history — which is what makes resumption possible.

## Layout

```
ws/runs/<run>/
    bus.db
    tasks/<task_id>/
        spec.json  outcome.json  transcript.jsonl  stderr-<agent>.log  tools/
```

Resumption is not a mode: a worker loads whatever transcript is already in its
directory. Point it at an existing directory to continue with history; give it a
new directory with the same spec for a clean retry.

## Constraints

Pyright strict with no `Any`, no `object`, and no JSON-blob types — JSON is text
until `model_validate_json` makes it a concrete model. One class per module.
No comments beyond a one-line header. See `CLAUDE.md`.

## Testing

```bash
uv run pytest tests/unit          # no network
uv run pytest tests/integration   # spawns real worker subprocesses
ANCALAGON_LIVE=1 uv run pytest tests/integration   # also calls a real model
```

The integration suite's offline test exercises the whole pipeline — CLI, bus,
supervisor, worker subprocess, outcome and stderr capture — up to the model
boundary, without a credential.

## Design

`docs/architecture.md` follows a single run through every file it touches, in order --
start there if you are reading the code.

`docs/superpowers/specs/2026-08-02-ancalagon-agent-harness-design.md` is the design
rationale: what was chosen, what was deliberately cut, and why.
