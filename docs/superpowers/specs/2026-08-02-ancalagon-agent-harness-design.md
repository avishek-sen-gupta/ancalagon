# Ancalagon — Agent Harness for Reverse Engineering

**Date:** 2026-08-02
**Status:** Design approved, not yet implemented

## Purpose

An agent harness for reverse engineering. Given one or more data structures and a goal, an agent either works the structure directly with tools, or generates a deterministic traversal program — plus the Pydantic contracts for its own analysis touch points — and runs that under supervision.

Which path is taken depends on the goal. Where the walk over a structure can be pinned down deterministically, it should be, and the model should be invoked only at the points where judgement is genuinely needed. Where the traversal itself requires judgement, an agent walks it with tools. Both paths use the same delegation primitive, so neither is privileged.

The structures are arbitrary: a document parsed to JSON, a control flow graph, an AST dump, a binary's symbol table. The only requirement is that a deterministic program can be written against them with LLM touch points.

## Non-goals

- Not a general agent framework. It is a toolkit of primitives, per `PHILOSOPHY.md`.
- Not distributed. Everything runs on one machine, in a handful of local processes.
- No streaming progress from running subagents. A running agent's transcript is a file; read it.
- No automatic retry, no compaction, no concurrency in v1.

## Architecture

Three kinds of process, communicating only through SQLite rows and files.

```
CLI ─┬─ root agent ──── INSERT task row ────▶ bus.db ◀─── SELECT/UPDATE ───┐
     │                  run_harness                                        │
     └─ supervisor ◀──── SELECT queued ──────┘                        supervisor
                    spawn / reap / kill-on-timeout / report                 │
                              │                                             │
                        worker (one Session)  ──▶ files                     │
                        harness (traversal)   ──▶ INSERT task rows ─────────┘
```

- **Root agent** — a `Session`. Reasons, uses tools, delegates, generates harnesses.
- **Worker** — one `Session` per process, one attempt at one task. Crashes in isolation.
- **Supervisor** — a plain loop, no LLM. The only place in the codebase that constructs `Popen`.
- **Harness** — agent-generated Python. A deterministic walk that delegates at touch points. No LLM client of its own.

### Communication

There is no IPC. No sockets, pipes, signals, or message broker.

- A parent delegates by writing `spec.json` and inserting a `queued` row. It never spawns anything and never holds a process handle.
- The supervisor claims queued rows, spawns, reaps, kills on timeout, and writes status back.
- A worker writes `outcome.json`, appends to `transcript.jsonl`, and exits.
- An agent learns of completions by querying at its own turn boundary.

Querying at the turn boundary costs nothing over a push notification, because an LLM cannot act between turns. Polling is only a cost when something could have reacted sooner.

Deterministic harness code *can* react sooner, but it also queries rows rather than waiting on process events, so that process liveness stays the supervisor's concern alone.

### What was deliberately cut

**`ask_parent`.** A subagent cannot ask its parent a question mid-run. It returns `NeedsInput` and stops; the parent decides what to do. This removes sockets, responder threads, question/answer protocols, resumption choreography, and every partial-failure question that came with them. A child can never block a parent, and a dead child cannot hang anything, because nobody holds a handle to it except the supervisor.

This is a real capability loss and is accepted knowingly. The prior art surveyed (Claude Code, LangChain background subagents, LangGraph `interrupt()`) either does not support child→parent escalation at all, or implements it via polling or checkpoint/resume — both of which were rejected on their own merits before that survey was run.

**Automatic restart.** The supervisor reports crashes; it never retries them. Retrying costs a fresh budget slice, so the parent must decide each retry is worth it. Auto-restarting an agent that crashed deterministically just spends the budget three times to reach the same failure.

The supervisor's one autonomous act is killing a wedged agent after a generous timeout, because a process that never exits cannot report anything and nobody else is positioned to act.

## Task model

The directory is the identity.

```
ws/runs/r_09/tasks/section_4_2/
    spec.json          the work
    transcript.jsonl   every attempt, appended, each line tagged with agent id
    outcome.json       latest result
    stderr-17.log      per agent
```

```
python -m ancalagon.worker --dir ws/runs/r_09/tasks/section_4_2 --agent-id 17
```

`agent-id` is the `tasks.id` row the supervisor inserted before spawning — a unique integer, no naming scheme to invent, and it joins straight back to the DB. Multiple attempts append to one transcript; each line carries its agent id, so `rg '"agent": 17'` isolates one attempt and the seam between attempts is visible where `seq` resets.

### Resumption

Resumption is not a mode. The worker loads whatever transcript is already in the directory.

```python
def main(dir: Path, agent_id: int):
    spec = AgentSpec.model_validate_json((dir / "spec.json").read_text())
    log = dir / "transcript.jsonl"
    messages = repair(load(log)) if log.exists() else []
    messages.append(user(spec.goal))
    Session(spec, messages, log, agent_id).run()
```

- **Continue with history** — point at the existing directory.
- **Clean retry** — new directory, same spec. Correct when the crash was caused by bad accumulated state.

`repair` is the only mechanical step: a transcript ending in an unanswered `tool_use` is rejected by the API, so the loader appends synthetic `interrupted` tool results. Synthesising rather than truncating is deliberate — the successor can see what its predecessor was reaching for when it died, which is often the most informative thing in the transcript.

Because a resumed agent's transcript already contains everything it inherited, chains flatten. One hop always yields the full history.

### Persistence

Every message is appended and flushed as it is produced, never written at exit:

```python
def append(self, m: Message):
    self.messages.append(m)
    self.log.write(m.model_dump_json() + "\n"); self.log.flush()
```

This is load-bearing. A killed agent's partial history must survive the kill or there is nothing to resume from. The root agent writes on the same discipline, so an entire run is reconstructible from disk after any crash, including the root's.

## Contracts

```python
InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT", bound=BaseModel)

class AgentSpec(BaseModel, Generic[InT]):
    task_id: str
    behaviour: str                 # how to work — becomes the system prompt
    goal: str                      # what to achieve
    input: InT                     # the slice this agent operates on
    output: str                    # "contracts.py:CaptionVerdict"
    budget: Budget
    tools: list[str] = []          # empty means everything permitted by config

class Completed(BaseModel, Generic[OutT]):
    value: OutT
    summary: str
    spent: Budget

class Exhausted(BaseModel, Generic[OutT]):
    value: OutT                    # the forced final answer
    summary: str
    spent: Budget

class NeedsInput(BaseModel):
    question: str
    summary: str
    spent: Budget

class Failed(BaseModel):
    error: str
    summary: str
    spent: Budget

class TimedOut(BaseModel):
    summary: str
    spent: Budget

Outcome = Completed[OutT] | Exhausted[OutT] | NeedsInput | Failed | TimedOut

class ToolResult(BaseModel):
    ok: bool
    summary: str                   # capped; what the agent sees inline
    path: Path                     # full output, always written
    byte_count: int
    truncated: bool
    error: str = ""
```

`Outcome` is a discriminated union rather than one model with a `kind` field, because a failed attempt has no value and a completed one has no error. A single model would need optional fields, and `None` is banned — the union states which fields exist in each case, so no caller ever inspects a field that cannot be there.

`output` names a class in the generated `contracts.py`. The worker resolves it by import, validates before writing, and the caller re-validates after reading, so the contract is enforced on both sides of the file and neither side trusts it blindly.

There is no JSON type anywhere in this. JSON exists as text in files; `model_validate_json` turns it into a concrete model at the boundary. The runtime-generated classes are handled by making the containers generic and resolving the class by import before validation — the type is late-bound, not unknown.

Tool failures are `ok=False` values, not exceptions. A bad `rg` pattern is something the agent reads and corrects; it never breaks the loop.

### Schema

```sql
tasks(id PK, dir, parent, status, pid, exit_code, summary, started, finished)
messages(id PK, ts, sender, addressee, kind, summary, ref_path)
cursors(consumer PK, last_seen_id)
```

**No column holds unbounded content.** Rows are metadata and pointers; bytes are files. This keeps `select *` readable in a terminal, which is the entire point of choosing SQLite — the run is inspectable mid-flight with `sqlite3` and `rg`, with no tooling of ours involved.

Multiple rows sharing a `dir` are the attempt history of one task. Task status is derived from its rows rather than stored twice.

WAL mode, `busy_timeout=5000`, one connection per process.

The `summary` columns carry a `CHECK (length(summary) <= 1000)`, so the no-unbounded-columns rule is enforced by the database rather than by convention. `status` carries a CHECK against the enum for the same reason.

### Migrations

Paired SQL files under `ancalagon/migrations/`, named `NNN_name.up.sql` and `NNN_name.down.sql`, with `PRAGMA user_version` as the schema counter — SQLite's built-in integer, so there is no metadata table to maintain.

```python
def migrate(conn: Connection, target: int) -> None:
    current = user_version(conn)
    steps = ups(current + 1, target) if target > current else downs(current, target + 1)
    for path in steps:
        conn.executescript(path.read_text())
```

Roughly 40 lines including file discovery.

The reason migrations exist here is not the usual one. `bus.db` is created per run and nothing is ever upgraded in place, so `up` on a fresh database is just schema creation. Their value is **reading old runs after a schema change**, which matters precisely because inspecting a completed run with `sqlite3` is a design goal rather than a debugging afterthought. That also makes `down` genuinely useful: it lets current tooling read a database written by a newer schema.

A run always migrates to the latest version on creation. Nothing migrates automatically on open — a mismatched `user_version` is reported, not silently repaired, because silently rewriting the schema of a completed run would destroy the record it exists to preserve.

## Budgets

Separate **turn** and **tool-call** budgets, allocated per attempt by the caller as a slice of its own remaining budget. Because the process boundary is the session boundary, a worker handed six turns physically cannot spend seven.

Exhaustion is a hard stop plus one forced final turn with tools stripped, instructing the agent to answer from what it has. The result is an `Exhausted[OutT]` carrying a real value rather than a truncation — which is why it has a `value` field at all, unlike `Failed` or `TimedOut`.

`max_depth` bounds nesting and counts agents, not processes — a harness is transparent to the count, so root is 0 and a touch-point agent is 1. Expected to be 1 in practice.

## Tools

| Tool | Notes |
|---|---|
| `ripgrep` | pattern + roots, JSON output mode |
| `ast_grep` | structural search, exploratory |
| `treesitter` | parse a file, emit AST as JSON |
| `sed` | stream only, never `-i` |
| `read_file`, `list_dir` | read scope |
| `write_file`, `edit_file`, `delete_file` | write scope only |
| `delegate`, `check_task`, `collect_task` | rows in `bus.db` |
| `run_harness` | row in `bus.db` |

**Every tool output is a file.** Results are written to `runs/<id>/tools/<seq>-<tool>.<ext>`; `ToolResult` carries a capped summary plus the path. The agent sees enough inline to decide and reaches for `read_file` or `ripgrep` when it needs detail.

`sed` being stream-only removes the entire class of "the agent mutated the artifact it was analysing", and transform-to-a-new-file is what generated code wants anyway.

### Workspace scoping

Two scopes, because reverse engineering means reading things you must not write to:

```toml
[workspace]
write_root = "./ws"
read_roots = ["/path/to/artifacts", "./ws"]
```

Enforcement is one function every path argument passes through: `Path.resolve()` first, then `is_relative_to()` against the allowed roots. Resolving first kills `..` traversal and symlink escapes together — a symlink inside the workspace pointing at `/etc` resolves outside `write_root` and is rejected.

## Configuration

TOML. Keys: `write_root`, `read_roots`, model and provider, default turn and tool-call budgets, `max_concurrent_agents` (defaults to 1 — v1 is sequential, and this is the single knob that makes it otherwise), `agent_timeout_s` (generous), `max_depth`, enabled tools, summary cap.

## Model access

LiteLLM, behind a local protocol so it is never called from `Session` directly:

```python
class LLM(Protocol):
    def complete(self, messages: list[Message], tools: list[dict]) -> Reply: ...
```

`LiteLLM` for real use, `FakeLLM` with scripted replies injected in tests. This confines provider quirks to one file and makes every unit test runnable with no network. LiteLLM's sync API is required; nothing in this system is async.

## Implementation constraints

Hand-rolled agent loop. No agent framework — the control flow is straight-line Python and a framework's `Agent`/`RunContext` model would fight the mutually-recursive script↔agent relationship.

**Ceiling: ~1100 LoC** excluding tests and SQL, relaxable with justification. The table below sums to 1110; treat any module exceeding its line as a signal to re-read the guardrails, not as licence to expand the total.

| Module | LoC | Module | LoC |
|---|---|---|---|
| `contracts.py` | 130 | `tools/search.py` | 90 |
| `session.py` | 150 | `tools/parse.py` | 80 |
| `supervisor.py` | 100 | `tools/files.py` | 90 |
| `bus.py` | 80 | `tools/harness.py` | 40 |
| `migrations.py` | 40 | | |
| `worker.py` | 50 | `tools/registry.py` | 50 |
| `llm.py` | 60 | `workspace.py` | 50 |
| `config.py` | 40 | `cli.py` | 60 |

Guardrails in `CLAUDE.md` apply: no gold plating, no comments beyond a one-line class header, few tests each covering a whole behaviour, fully typed with no `Any`.

Pyright runs in strict mode and must pass with zero errors. Strict catches implicit `Any` (unknown parameter, member, and return types) and bare untemplated generics such as `dict` or `list` in signatures, via `reportMissingTypeArgument`. It flags neither *explicit* `Any` — a basedpyright feature — nor `object` annotations nor JSON-blob aliases, so a `check-type-hygiene` pre-commit hook bans all three by pattern.

The design consequence is in the Contracts section: `AgentSpec` and the `Outcome` union are generic over the runtime-generated model classes rather than carrying JSON. `Any`, `object`, and `JsonValue` are all ways of declining to name a type that is in fact knowable — it is merely late-bound, and importing the generated module binds it.

## Testing

Eight tests. One per coherent behaviour, each asserting everything that behaviour implies.

| Test | Covers |
|---|---|
| `test_workspace_scoping` | `..`, symlink escape, absolute path outside, read-root not writable |
| `test_budget` | slice, decrement, exhaustion, forced final turn with tools stripped |
| `test_session_loop` | `FakeLLM`: tool call → result → completion → outcome written |
| `test_contracts` | spec/outcome round-trip, `output` class resolution, validation failure |
| `test_repair` | transcript ending mid-`tool_use` gets synthetic interrupted results |
| `test_bus` | insert, claim-once under two consumers, cursor advance |
| `test_migrations` | up to latest then down to 0 is a round trip; status and summary CHECKs reject bad rows |
| `test_supervisor` | queued→running→completed, crash→crashed, timeout→killed |
| `tests/integration/test_end_to_end` | small JSON, generated harness, one real agent |

Only the last hits the network.

## Build order

The substrate is useful whether or not the central bet pays off, and is roughly 600 of the total. Build it first.

1. `contracts`, `config`, `workspace`, `bus`, `migrations`
2. `llm` with `FakeLLM`, `session`, `worker`
3. `supervisor`, `cli`
4. Tool set
5. `run_harness` and codegen prompting

Then test the bet on a bottom-up graph annotation — a structure with a computed traversal order and a per-node LLM step, which is the regime where a generated program should most clearly win. The question is not whether the pattern works, it is whether the agent writes it correctly: right order, cycles condensed, child results actually awaited, memoisation present.

Compare against a hand-written traversal over the same structure and goal. If the generated one is wrong in ways the outputs do not reveal, that is the finding, and a working multi-agent harness remains either way.

## Known limitations

**Context grows monotonically** across resumptions. There is no compaction; the budget is the only bound. The mitigation is conventional rather than technical: a `NeedsInput` follow-up should usually be a new task with a small input slice, and resumption reserved for cases where accumulated exploration is the point.

**Generated traversals are agent-authored code** and can be silently wrong in ways the results do not reveal. Every output being a file is part of the mitigation; the other part is that harness edits are diffed into the transcript, so a rewrite after a crash is visible rather than inferred.

The sharpest instance is **cycles**. A generated traversal that walks a cyclic graph as if it were a DAG will recurse forever, deadlock waiting on a result that depends on itself, or quietly emit summaries built from empty children. Nothing in the harness detects this — condensing strongly connected components is the generated code's responsibility, and it must be an explicit requirement in the codegen prompting rather than something the agent is trusted to remember.

**The central bet is that traversals can be *generated*, not that they work.** Deterministic traversal with per-node LLM annotation is well established — GraphRAG summarises graph communities bottom-up, RAPTOR recursively clusters and summarises, and hierarchical summarisation over call graphs and ASTs is routine. Where traversal order is structurally determined (bottom-up annotation, dataflow propagation, any fixpoint), a program plainly beats an agent walking freehand: order is computed rather than judged, child results are a hard dependency, and no agent orchestrates five hundred nodes in one context window.

In all of that prior art the pipeline is hand-written by engineers and the model only fills the touch points. What is unproven here is that the **agent authors the traversal and its contracts in situ** from a goal and a structure, and that the generated code is correct often enough to trust. "Code as Agent Harness" (arXiv 2605.18747) covers code as an executable substrate but explicitly not LLM-generated orchestration that instantiates sub-agents, and flags executable contracts constraining agent behaviour as underspecified.

The separate open question is the regime where traversal order is itself a judgement — "find the parts of this document worth analysing" — where an agent exploring with tools may beat any generated walk.

**This is a poor-man's OTP.** The supervision model is deliberately Erlang-shaped — isolate, let it crash, let a supervisor decide — but with OS-process granularity and a hand-rolled supervisor, not microsecond spawns and millions of processes. Where genuine OTP semantics are wanted, Elixir already has them.

## Deferred

Concurrent fan-out, sibling messaging, parent→child steering, role-based addressing, transcript compaction. None are foreclosed: all of them are rows and files, and each is additive to what is specified here.

Concurrency is the one with a concrete motivating case already identified. In a bottom-up annotation, nodes at the same topological depth are independent by construction — the dependency structure itself states the safe fan-out — and a sequential walk over a few hundred nodes pays a process spawn plus a multi-turn agent for each. That is `max_concurrent_agents > 1` plus level-batched spawning, and it should be the first deferred item revisited.
