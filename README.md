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

A driver running one item at a time sets the per-run values in the config instead:

```toml
[run]
run_dir = "./ws/runs/item-0001"  # reused on a second invocation, which continues the transcript
goal_file = "./ws/runs/item-0001/goal.md"
contract = "./shape.py:Answer"   # the root answers in this shape, not free text
```

`--goal` and `goal_file` are alternatives; give exactly one. An empty `run_dir` allocates the next
`runs/r_NNNN` as before. A missing or empty `goal_file`, or a `contract` whose module or class is
not there, exits 2 without starting a run.

Keep a named `run_dir` under `<write_root>/runs/` as above: the watcher below only sees
`<write_root>/runs/*/tasks/*` and `<write_root>/*/tasks/*`, and a run elsewhere is invisible to it.

Watch a run as it happens, including subagents spawned mid-run:

```bash
./scripts/ancwatch.zsh ancalagon.toml    # start before or during a run
```

Give it the same config the run uses and it watches that config's `write_root`, so
the two cannot disagree about where runs live. A directory works too.

On Bedrock with a bearer token, `scripts/ancrun.zsh` runs the same command with
stale AWS credentials stripped from the environment — otherwise litellm signs with
those instead and Bedrock rejects the request.

`run` brings its own run database up to the latest schema before opening it, so an existing
run directory keeps working after an upgrade. Nothing else migrates: opening a bus to read
one requires it to be current already. To upgrade a database without starting a run:

```bash
ancalagon migrate --db ws/runs/r_0001/bus.db          # to the latest version
ancalagon migrate --db ws/runs/r_0001/bus.db --to 1   # or back down to a given one
```

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

Stopping is not giving up. Answer it and it continues from where it left off, with
everything it had already worked out:

```bash
ancalagon answer --run-dir ws/runs/r_0001 --task 1 --answer "keep both captions"
ancalagon run --config ancalagon.toml          # same run_dir; picks it up
```

A parent can do the same to its own child mid-run with the `answer_task` tool, and a
parent that cannot answer passes the question up by asking one itself. Meanwhile the
other children keep working — so by the time you answer, their results are waiting.

## Inspecting a run

Everything is on disk and in one SQLite file:

```bash
sqlite3 ws/runs/r_0001/bus.db \
  "select agent, status, source, summary from agent_events order by id"
rg '"agent": 17' ws/runs/r_0001/tasks/*/transcript.jsonl
```

Every model call is recorded too, so a run can be asked what it consumed and
which agent consumed it:

```bash
sqlite3 -json ws/runs/r_0001/bus.db \
  "select agent, model, sum(prompt_tokens), sum(completion_tokens),
          sum(cache_creation_tokens), sum(cache_read_tokens)
   from model_calls group by agent"
```

Tokens are recorded; money is not. Cost needs a price list that changes without
notice, and a figure computed at one week's prices is silently wrong the next.
The counters are facts the provider reported; pricing them is the caller's job.

Transcripts are appended and flushed per message, so a killed agent leaves a
readable partial history — which is what makes resumption possible.

## Layout

```
ws/runs/<run>/
    bus.db                        tasks, agents, an append-only event log, model calls
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
