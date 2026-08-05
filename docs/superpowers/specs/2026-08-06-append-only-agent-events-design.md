# Append-Only Agent Events

**Date:** 2026-08-06
**Status:** Design approved, not yet implemented
**Amends:** the schema in `2026-08-02-ancalagon-agent-harness-design.md`. Everything else in that spec stands.

## Why

Two defects, found by reading a real run rather than the code.

**The `tasks` table is a table of agents.** Its rows are executions, not work items: several rows share one `dir` once a task is retried, and `tasks.id` is what gets passed as `--agent-id` and written as the `agent` field on every transcript line. The task is the directory — it owns `spec.json`, `contracts.py` and `transcript.jsonl`. The name has been describing the wrong entity, which is why `parent`, `depth_of` and `agent_id` all read slightly against the grain.

**The row records the process, not the agent.** A worker writes `outcome.json` and returns 0 whatever the agent produced, so the supervisor marks the row `completed`. From a run that failed:

```
outcome.json kind : failed
bus row status    : completed  exit_code 0
```

`needs_input` is recorded the same way. So the obvious query is wrong:

```sql
select * from tasks where status != 'completed'   -- misses every failed agent
```

The only way to know how a run went is to open every `outcome.json`. Worse, the row is mutated in place, so the history is destroyed as it goes: a task that was queued, ran, asked a question and exited leaves a single row saying `completed`.

## The model

Three entities, each with one job.

```sql
tasks(id PK, dir UNIQUE, parent_agent, created)      -- the work
agents(id PK, task FK, created)                      -- one execution of it
agent_events(id PK, agent FK, ts, status, source,    -- append-only history
             pid, exit_code, summary)
```

**Task** — a directory holding `spec.json`, `contracts.py`, `transcript.jsonl` and `tools/`. Created once. Retrying a task adds an agent, not a task.

**Agent** — one execution. Gets a process, an `--agent-id`, and its own lines in the transcript. `agents.id` is the integer already visible in transcripts, `check_task` and `collect_task`, so nothing downstream renumbers.

**Event** — one observation about an agent. Never updated, never deleted.

`parent_agent` records which execution delegated the work, which is more informative than naming the parent task, and `depth_of` walks agent → task → parent agent.

## Statuses

The vocabulary is the union of what each party can observe.

| Status | Source | Meaning |
|---|---|---|
| `queued` | supervisor | enqueued, awaiting a slot |
| `claimed` | supervisor | taken by a supervisor, not yet spawned |
| `running` | supervisor | process spawned, `pid` recorded |
| `completed` | worker | the agent answered and it validated |
| `needs_input` | worker | the agent stopped to ask |
| `exhausted` | worker | budget spent, forced answer given |
| `failed` | worker | the agent produced no valid answer |
| `crashed` | supervisor | non-zero exit |
| `timeout` | supervisor | killed after `agent_timeout_s` |
| `abandoned` | supervisor | orphaned or killed at shutdown |
| `exited` | supervisor | process ended; `exit_code` carries the detail |

The worker group is `OutcomeKind` minus `timed_out`, so the database finally agrees with `outcome.json` instead of contradicting it.

## Who writes what

Both parties always append; neither overwrites the other. A stalled agent reads:

```
queued       supervisor
running      supervisor  pid=76207
needs_input  worker      "which caption wins?"
exited       supervisor  exit_code=0
```

Nothing here contradicts anything else. "The process exited 0" is true and should not be erased by the agent's account, and the agent's account should not be erased by the process's. The `source` column exists so the log explains itself, not to create a second notion of status.

**Current status is the latest event**, which after a clean run is the supervisor's `exited`. That is honest: the process did exit. The agent's outcome is one row above and is now queryable, which was the point.

**Liveness** — the question every caller actually asks — is derived instead: an agent is in flight until it has an event from the terminal set (`completed`, `needs_input`, `exhausted`, `failed`, `crashed`, `timeout`, `abandoned`, `exited`). `Bus.active_for(dir)` becomes a query for tasks whose latest agent has no terminal event.

## Consequences

**No denormalised status.** `tasks` and `agents` hold immutable facts only. Every status question derives from `agent_events`, so nothing can disagree with itself. The cost is a subquery in `bus.py` and longer ad-hoc SQL; the gain is that append-only is true of the schema and not just a convention.

**The worker writes to the bus.** It already opens `Bus` for `depth_of`, so this adds a call rather than a dependency. It appends its outcome event immediately before writing `outcome.json`, so the two cannot diverge.

**`delegate`'s retry guard keeps working unchanged in spirit**: refuse while an agent is in flight, allow once terminal. The query moves from a `status IN (...)` column test to a latest-event test.

## Migration

None. The project is not in production, so `001_init` is rewritten in place and existing
run databases are discarded rather than upgraded. That removes the one genuinely delicate
part of this change — preserving agent ids across a split, because transcript lines and
`stderr-<id>.log` names already reference them on disk.

## Testing

Three behaviours, in the project's style.

**`test_migrations`** covers the round trip against the rewritten schema: up creates the three tables with their CHECK constraints, down drops them.

**`test_bus`** covers the append-only lifecycle: enqueue creates task, agent and `queued`; claim appends `running`; a worker event and a supervisor event both land and neither overwrites; `active_for` sees an agent as live until a terminal event and not after; a retried task has two agents and one directory.

**`test_supervisor`** is unchanged in intent but asserts against events rather than a mutated row.

## Not in scope

No change to `outcome.json`, the transcript format, the tool set, or the agent loop. No new statuses beyond those listed. No pruning or compaction of events — a run's event count is bounded by a few per agent, and the file is already disposable per run.
