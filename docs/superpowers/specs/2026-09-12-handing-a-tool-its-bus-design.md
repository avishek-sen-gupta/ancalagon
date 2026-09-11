# Handing a tool its bus

## The problem

Six tools open a database nobody gave them. Five do it inline:

```python
bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
```

`idle`, `check_task`, `collect_task`, `delegate_to` and `watch_file` each build one inside `run`.
The sixth, `answer_task`, calls `ancalagon/answer.py`, which does the same at line 54.

The previous spec declared the `Bus` protocol and `NoBus`. Neither has a caller: nothing can be
handed a bus, so nothing can be denied one. This spec does the handing.

Two things follow from it. A tool's real dependencies become visible at its construction site —
`check_task` currently declares three and uses one. And a `Session` given `NO_BUS` genuinely cannot
reach a database, which is what the next spec needs.

## What this is not

**Not `session_for`.** Assembling a single in-process `Session` is the next spec. This one only
makes `NO_BUS` mean something.

**Not a change to what any tool does with a real bus.** Every behaviour under a `LifecycleStore`
is unchanged. What changes is where the bus comes from, and what happens when there is not one.

**Not a uniform constructor surface.** There is no such thing today — six tools have five distinct
shapes — and this spec does not invent one. Each tool ends up declaring what it uses.

## The constructors

```python
CheckTask(bus)
CollectTask(bus, fs)
Idle(bus, agent)
AnswerTask(bus, parent, clock, fs)
WatchFile(bus, role, run_dir, parent, fs)
DelegateTo(bus, role_name, role, run_dir, parent, fs)
```

`clock` leaves five of the six: it existed only to satisfy `LifecycleStore.open`. `check_task` goes
from three declared dependencies to one, which is the invisibility this spec set out to remove.

Two more, each one annotation:

- `children/bus_children.py:9` — `BusChildren.__init__` takes a `LifecycleStore` and calls only
  `snapshot()`. Widen to `Bus`.
- `tools/delegate/collect_task.py:70,83,102` — helpers annotated `bus: LifecycleStore`. Widen to
  `Bus`.

## The decision belongs at construction

Two tools write to disk before they enqueue:

```python
self.fs.mkdir(task_dir, parents=True, exist_ok=True)
self.fs.write_text(task_dir / "spec.json", spec.model_dump_json())
queued = bus.enqueue(task_dir, parent_agent=self.parent)
```

Under `NO_BUS` that leaves `run_dir/tasks/<id>/spec.json` with no queue row — an orphan a later
real run would scan and treat as a live task.

**`available_tools` chooses the tool instead of the tool choosing a branch.** It knows which bus it
holds, so it decides once:

```python
bound_for(DelegateTo(bus, role_name, role, run_dir, parent, fs), role)   # a real bus
bound_for(NoDelegateTo(role_name, role), role)                           # NO_BUS
```

`NoDelegateTo` and `NoWatchFile` carry the same `name`, `description`, `cost` and `args_model` as
their counterparts, so the schema the model sees is identical and it learns the truth from a
failure rather than from a missing tool. They hold no `fs` and no `run_dir`. They cannot write.

The orphan directory is therefore impossible rather than guarded: no runtime check inside any
`run`, no cleanup path, no ordering race. This is the codebase's own rule — resolve a decision into
an executable object early in the call chain, then inject it — rather than an exception to it.

Three alternatives were considered and rejected:

- **A `bus is NO_BUS` check inside `run`.** Works, and costs the polymorphism `NoBus` exists for. A
  third implementation — a test fake, a future read-only bus — passes the identity check and writes
  anyway.
- **Write, then delete on `NoAgentRef`.** A compensating transform on a failure path, which
  `refactoring.md` names as a sign the model is wrong; a crash between write and delete still
  orphans.
- **Enqueue first, write after.** No half-state, but a live supervisor polls every 50ms and can
  claim the row before `spec.json` lands, spawning a worker that fails reading it. It trades a
  `NO_BUS`-only wart for a race on the path that actually runs.

The `AgentRef | NoAgentRef` match on `enqueue`'s return stays. The construction-time choice covers
the singleton; the match is the type-level obligation that covers everything else. Neither replaces
the other: the choice cannot see a third implementation, and the match cannot un-write a file.

## The four that need no variant

Measured, not assumed:

| tool | under `NO_BUS` |
|---|---|
| `check_task` | empty snapshot; `args.task not in snapshot.task_by_agent` → `ctx.failure("no agent N")` |
| `collect_task` | the same check, the same failure |
| `idle` | empty snapshot → no live children → proceeds, which is correct for an agent running alone |
| `answer_task` | `_asked` raises `KeyError("no agent N")` at `answer.py:25` **before** the transcript write, and `AnswerTask.run` already catches `(KeyError, ValueError)` into `ctx.failure` |

`answer_task` is the one worth stating explicitly, because it also writes before enqueueing and
looks like it needs a variant. It does not: the guard that rejects an unknown agent runs first.

## Threading

`bus: Bus` follows the path `web: WebClient` took:

```
worker.main            already holds bus = LifecycleStore(conn, clock) at worker.py:186
  build_registry(..., bus)          11 call sites across 7 files
    available_tools(..., bus)       the real-or-null choice lives here
      delegate_tools(..., bus)      drops clock
```

`depth_of(bus.snapshot(), agent_id)` at `worker.py:222` already reads the bus outside
`build_registry`, so it is unaffected.

Off that path, `answer.py::answer_task` takes a `Bus` and drops `run_dir` and `clock`. `run_dir`
existed only to locate `bus.db`. `answer_command.py` then builds the `LifecycleStore` itself, which
is honest: it is a CLI entry point that already owns `RealFileSystem()` and `SystemClock()`.

Measured blast radius: 11 `build_registry` calls in 7 files, and 22 direct tool constructions in
tests.

## Testing

The two tests the previous spec could not write become possible here, and they are the point.

- `DelegateTo` under `NO_BUS` resolves to `NoDelegateTo`: the registry offers a tool of the same
  name whose `run` returns `ok=False` naming the task it could not queue, **and `tmp_path` is
  empty afterwards**. That last assertion is what proves the orphan directory is impossible rather
  than cleaned up.
- `WatchFile` under `NO_BUS` does the same.
- `check_task`, `collect_task`, `idle` and `answer_task` under `NO_BUS` each return the failure the
  table above names — one test covering the four, since they share the behaviour.
- The existing tests for all six under a real `LifecycleStore` keep their assertions unchanged.
  A tool's behaviour with a bus is not what this spec alters.

No mocking. `NO_BUS` is the injected fake, which is the point of having built it.

## Units of work

1. `Bus` threaded through `build_registry`, `available_tools` and `delegate_tools`; the six tools
   take it; dead `clock`, `run_dir` and `fs` parameters removed; `BusChildren` and
   `collect_task`'s helpers widened to `Bus`.
2. `NoDelegateTo` and `NoWatchFile`, and the construction-time choice in `available_tools`.
3. `answer_task` takes a `Bus`; `answer_command` builds one.

## What follows

**Spec C** adds `session_for`, assembling a single in-process `Session` from a `Config` — the
fifty lines `worker.py` currently spells out, with `NO_BUS`, `NO_CHILDREN`, `NO_LETTERBOX` and
`UNMETERED` as the defaults that make one agent run alone.
