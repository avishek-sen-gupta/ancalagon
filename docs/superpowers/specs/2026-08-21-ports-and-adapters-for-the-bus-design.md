# Ports and adapters for the bus

## The problem

`Bus` is thirty methods holding four different jobs: it opens the database, builds and runs
queries, decides domain questions, and enforces the lifecycle. The project's stated architecture
is ports and adapters with a functional core, and `Bus` is where that stopped being true.

About a third of its surface is domain logic that happens to live next to the SQL:

- `outstanding`, `uncollected`, `live_children` — parent and child lifecycle rules
- `_is_news`, `_has_news`, `wakeable` — scheduling policy
- `unreaped`, `active_for` — "is this attempt still going"

None of those are storage. Each is a pure function of an agent's events and a task's children,
written as a query-adjacent method because that is where the rows were.

That placement has a cost beyond tidiness. `wakeable` loops every task, then every child, and for
each child issues three queries — newest agent, its history, its newest event id. The supervisor
runs it twenty times a second. **The N+1 and the layering are one defect**: the predicate is
implemented one row at a time because it lives where rows are fetched one at a time.

The same shape produced a real bug this week. `claim` and `queued_count` asked the same question
two different ways, and only one consulted the fold; the disagreement would have hung the
supervisor.

## The constraint

Stated by the project owner, and machine-checked rather than conventional:

1. A couple of database access classes, split so each covers a domain that makes sense. All reads
   and writes go through them.
2. Orchestrators use those classes.
3. The domain is pure.
4. **Domain logic does not import adapters.** Only orchestration may hold both.

## The shape

```
contracts            HarnessTask, Snapshot, AgentEvent, CallUsage        (data)
   ↑
attempt, schedule    the fold, and every predicate over a Snapshot       (pure)
   ↑
bus                  LifecycleStore, MeterStore                          (adapters)
   ↑
supervisor, tools,   fetch, then decide
answer, cli, worker
```

`attempt` and `schedule` import only `contracts`. They never import `bus`. The adapters import
`contracts` and `attempt` — `record` needs the transition table — but never `schedule`.
Orchestrators import both sides.

## The two adapters

The schema splits cleanly in two.

`tasks`, `agents` and `agent_events` are one aggregate: a task has agents, an agent has events,
and the snapshot spans all three. Splitting them would fragment it.

`model_calls` is unrelated — token accounting, written by workers as they run, read by the CLI
for reporting. It already has a port, `Meter`, with `BusMeter` as its adapter; today that adapter
borrows the whole of `Bus` to reach one table.

| Adapter | Owns | Surface |
|---|---|---|
| `LifecycleStore` | `tasks`, `agents`, `agent_events` | `snapshot`, `record`, `enqueue`, `claim`, `history`, `task`, transactions |
| `MeterStore` | `model_calls` | `record_call`, `calls`, `tokens_by_agent` |

**They share one connection.** A small opener applies the pragmas, checks the schema version, and
constructs both over it:

```python
conn = _connect(path)
lifecycle = LifecycleStore(conn, clock)
meter = MeterStore(conn, clock)
```

The consequence is worth stating because it is the reason a shared connection is a choice rather
than an obvious default: `record`, `enqueue` and `claim` wrap their work in
`BEGIN IMMEDIATE … COMMIT`, and anything else executing on that connection while a transaction is
open joins it. A metering write would then commit or roll back with the lifecycle write. That is
unreachable today — the process is single-threaded and nothing meters mid-transaction — so the
independence rests on inspection rather than construction. Separate connections would make it
structural at the cost of a token write occasionally waiting on the write lock. Shared was chosen.

## The snapshot

`Bus.snapshot()` becomes the only way to read lifecycle state. Three queries — all tasks, all
agents, all events — folded once into a frozen value in `contracts`:

```python
class Snapshot(pydantic.BaseModel, frozen=True):
    tasks: tuple[HarnessTask, ...]
    agents_by_task: Mapping[int, tuple[int, ...]]     # ordered, newest last
    events: Mapping[int, tuple[AgentEvent, ...]]
    attempts: Mapping[int, Attempt]                   # folded at build
```

`attempts` is derived from `events` and computed once at construction. It is not a second source
of truth — the value is immutable, and folding per call would repeat work every predicate does.

Every caller loads a snapshot, including the one-shot ones. The tools that touch the bus —
`delegate_to`, `collect_task`, `check_task`, `idle` — plus `answer` and `BusChildren` are all
coordination primitives: they ask about the shape of the run, not about one row. A uniform way to
ask is worth more than the reads saved by a narrow query, and two ways to ask the same question is
exactly what produced the `claim`/`queued_count` divergence.

**The trade.** A tick goes from roughly `tasks × children × 3` queries to three, but it reads
every event each time, so cost grows with the log rather than with what changed. At a hundred
agents that is a few hundred rows per tick — nothing. At several thousand it starts to matter, and
the log being append-only means an incremental refresh is available if it ever does. Not built
now: it would put mutable cached state in the supervisor, which this codebase is careful about,
and staleness bugs are worse than reads.

## The pure package

`ancalagon/schedule/` holds every predicate, each taking a `Snapshot`:

`newest_agent`, `outstanding`, `uncollected`, `live_children`, `active_for`, `unreaped`,
`wakeable`, and the `is_news`/`has_news` pair behind it.

They are ordinary functions over a frozen value, so they test without a database, a temporary
directory or a clock — which is what makes the scheduling rules readable for the first time.

## What stays in the adapter

**`record` keeps the gate.** It derives the current attempt, calls the pure `next_state`, and
refuses an illegal write, all inside the transaction that performs it. The *rule* lives in the
core; only the enforcement point sits at the write.

Moving the check to callers would satisfy the letter of the separation and lose the property the
previous branch was built to get: that an illegal sequence is unwritable by anyone, including a
caller who forgets. A single choke point is the enforcement.

`record` folds from its own read rather than from a caller's snapshot. A write validated against a
snapshot would be validated against whenever that snapshot was taken.

## Names

`TaskRow` becomes `HarnessTask` and moves to `contracts`. `Row` names a row of a table; once the
pure functions reason about it, the storage name is the same kind of leak as a SQL fragment
travelling as a string.

`AgentState` is a join result, not a stored row — agent, task, dir, plus the latest event's
status, pid and summary. Under the snapshot its callers have `attempts` and `events`, which carry
what it was standing in for, and its "latest event" fields are the shape this codebase has been
removing all week. **It is expected to be deleted rather than moved.** If a caller genuinely needs
it, that caller is named in the plan and the reason recorded.

## The contracts

Three, all in `pyproject.toml`, all failing the build rather than a review.

1. **Layers** — the existing contract, updated for `schedule` and the adapter split.
2. **Domain must not import adapters** — `forbidden`, from `ancalagon.attempt` and
   `ancalagon.schedule` to `ancalagon.bus`.
3. **No SQL outside the adapters** — `forbidden`, to `sqlite3` and `sqlalchemy`, from every
   package except the two store modules.

Two mechanics were verified against this repository rather than assumed, because an unenforced
contract reads as protection while providing none:

- Forbidding an external package requires `include_external_packages = True`. Confirmed: without
  it the contract silently passes.
- `forbidden` follows indirect chains by default, so contract 3 flags
  `supervisor → bus → sqlalchemy` — true of every orchestrator, and not what is meant.
  `allow_indirect_imports = True` restricts it to direct imports, which is the intent. Confirmed
  both ways against the current tree.

## What this does not change

The migrations stay raw SQL in `001_init.up.sql`, applied as they are now. SQLAlchemy stays a
query builder: no ORM, no Engine, no session. Execution stays on the stdlib `sqlite3` connection,
and `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` stay raw, because the write-lock timing is depended upon
and a leaked lock in that code was fixed this week.

No behaviour changes. Every test count is identical before and after; an expectation that needs
changing means a query moved and is a finding, not a fix.

## Residuals

- The snapshot reads the whole event log per tick. Incremental refresh is available and deliberately
  not built.
- The two adapters share a connection, so their transactional independence is by inspection.
- `Bus.record` still issues its own read to fold the current attempt, one query per write.
