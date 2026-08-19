# Idling Parents (Revised) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wake an idling parent when a child of its task settles, and hold the parent to account for reading what its children returned.

**Architecture:** Every parent-facing question reduces to one predicate asked of a **task**, not an agent — `outstanding(T)`, which reads the newest agent's *history* rather than its last row. Children resolve through every agent of the parent's task. `collect_task` records consumption. Tool narrowing moves from once-per-attempt into the turn loop behind an injected `Children` port, which collapses `_final_turn` into `Session.run`. The supervisor evaluates a wake predicate each tick instead of firing an event when work ends.

**Tech Stack:** Python 3.13, Pydantic v2, SQLite (stdlib), pytest, Pyright strict.

**Spec:** `docs/superpowers/specs/2026-08-19-idling-parents-revised-design.md`

## Global Constraints

- Pyright strict, **zero errors**. `Any` banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and hand-rolled recursive JSON types banned for the same reason.
- Every generic parameterised: `list[AgentState]`, never bare `list`; `tuple[int, ...]`, never bare `tuple`.
- **No comments** except a one-line header on a class or module. No docstrings, no inline explanations, no section dividers, no TODOs.
- All Pydantic models `frozen=True`. One class per file. Fully qualified imports, no relative imports.
- A class implementing a `Protocol` **inherits** it, so the error lands on the broken class.
- `Sequence`/`Mapping` from `collections.abc` for parameters that are not mutated.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance`, no bare `except`, no workaround guards.
- **Never ask an agent's *latest* status what happened to it.** A worker records its own account and the supervisor appends `exited` over it, so an idled agent and a completed one are the same row by latest status — verified. Ask whether the history *contains* what you care about.
- **Never ask an *agent* a question about a *task*.** `tasks.parent_agent` is written only when the task row is new, so it names whichever attempt happened to create the child. Resolve through every agent of the parent's task.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file. Concrete assertions (`assert result == 30`), never `assert x is not None`.
- **No mocking.** `unittest.mock.patch` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, fake spawners.
- A shipped migration is never edited. Add a numbered one.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`.
- The `python-fp-lint` pre-commit hook lints **staged content of staged files**, so it reports pre-existing debt in any older file a change touches. Run `pre-commit run --all-files` with work **staged** — unstaged changes are stashed and give a false pass. `--no-verify` only for violations on lines your diff does not modify, stated in the commit message. **Never `git stash` mid-verification** — an earlier implementer did and silently committed half its work.
- If Talisman flags a file, **append** to `.talismanrc` using the checksum Talisman reports; never remove or overwrite an existing entry.
- Never reference an external codebase in a tracked artifact.

---

## File Structure

**Created**
- `ancalagon/bus/outstanding.py` — nothing; the predicate lives on `Bus` (listed here only to say it deliberately does not get its own module, since it is three queries over one connection).
- `ancalagon/session/children.py` — the `Children` protocol.
- `ancalagon/session/bus_children.py` — `BusChildren`, the bus-backed implementation.
- `ancalagon/session/no_children.py` — `NoChildren`, the null object.
- `ancalagon/migrations/005_collected_status.up.sql` / `.down.sql` — the `collected` status.

**Modified**
- `ancalagon/bus/bus.py` — `child_tasks`, `outstanding`, `live_children` rewritten, `wakeable`; `resumable_idle` and `latest_agent` deleted.
- `ancalagon/bus/agent_status.py` — `COLLECTED`.
- `ancalagon/tools/delegate/collect_task.py` — records `collected`.
- `ancalagon/tools/idle/idle.py` — asks `outstanding`, not `live_children`.
- `ancalagon/worker.py` — `build_registry` stops narrowing; injects `BusChildren`.
- `ancalagon/session.py` — per-turn narrowing; `_final_turn` collapsed into `run`.
- `ancalagon/supervisor/supervisor.py` — `_wake_idling` appended to `tick`.
- `README.md`, `docs/architecture.md`.

**Deleted**
- `Bus.resumable_idle`, `Bus.latest_agent` — built for the event-driven design, no caller here.
- `Session._final_turn` — collapsed into `run`.

---

### Task 1: A task knows its children and whether it is outstanding

**Files:**
- Modify: `ancalagon/bus/bus.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Produces: `Bus.child_tasks(task: int) -> list[TaskRow]`, `Bus.outstanding(task: int) -> bool`, and `Bus.live_children(agent: int) -> list[AgentState]` rewritten to resolve through the task.
- Deletes: `Bus.resumable_idle`, `Bus.latest_agent`.

This task fixes **both committed Critical bugs**. It touches no behaviour above the bus, so the suite either stays green or names exactly what depended on the broken semantics.

`outstanding` reads the newest agent's *history*, not its latest status, because `exited` masks `idling`. `child_tasks` resolves through every agent of the parent's task, because `parent_agent` is frozen at task creation.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_bus.py`, following the fixture style already in that file:

```python
def test_a_task_sees_children_from_every_attempt_and_knows_when_it_is_outstanding(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    first = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    early = bus.enqueue(tmp_path / "early", parent_agent=first)

    assert [s.agent for s in bus.live_children(first)] == [early]
    assert bus.outstanding(bus.state(early).task) is True

    bus.record(first, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(first, AgentStatus.EXITED, EventSource.SUPERVISOR)
    woken = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    late = bus.enqueue(tmp_path / "late", parent_agent=woken)

    assert sorted(s.agent for s in bus.live_children(woken)) == [early, late]

    bus.record(early, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(early, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [s.agent for s in bus.live_children(woken)] == [late]
    assert bus.outstanding(bus.state(early).task) is False

    bus.record(late, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(late, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.outstanding(bus.state(late).task) is True
    assert [s.agent for s in bus.live_children(woken)] == [late]
```

Four things are load-bearing. `live_children(woken)` must include `early`, created by an *earlier* attempt — that is Critical bug 1. The `EXITED` record after every terminal status is what production writes. `outstanding(early's task) is False` after it completed. And `outstanding(late's task) is True` after it *idled*, even though its latest status is `exited` — that is Critical bug 2.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k every_attempt -v`
Expected: FAIL with `AttributeError: 'Bus' object has no attribute 'outstanding'`.

- [ ] **Step 3: Implement**

```python
    def child_tasks(self, task: int) -> list[TaskRow]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE parent_agent IN "
            "(SELECT id FROM agents WHERE task = ?) ORDER BY id",
            (task,),
        ).fetchall()
        return [TaskRow.model_validate({k: r[k] for k in r.keys()}) for r in rows]

    def outstanding(self, task: int) -> bool:
        newest = self.conn.execute(
            "SELECT MAX(id) AS agent FROM agents WHERE task = ?", (task,)
        ).fetchone()["agent"]
        statuses = {e.status for e in self.history(int(newest))}
        return AgentStatus.IDLING in statuses or not (statuses & TERMINAL)

    def live_children(self, agent: int) -> list[AgentState]:
        task = self.state(agent).task
        return [
            self.state(self._newest_agent(t.id))
            for t in self.child_tasks(task)
            if self.outstanding(t.id)
        ]
```

`_newest_agent(task) -> int` is a private helper returning `MAX(agents.id)`; `outstanding` uses it too.

`not (statuses & TERMINAL)` is the in-flight case: an agent that has only `queued`/`claimed`/`running` events has not ended. `TERMINAL` is unchanged and keeps its current meaning.

- [ ] **Step 4: Delete what this replaces**

Delete `Bus.resumable_idle` and `Bus.latest_agent`, then `grep -rn "resumable_idle\|latest_agent" ancalagon tests` and remove every reference, including in tests written for them.

- [ ] **Step 5: Run tests, verify**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`

- [ ] **Step 6: Mutation-check**

Three mutations, all must fail. Revert `live_children` to `WHERE t.parent_agent = ?` and confirm the `[early, late]` assertion fails — that is Critical bug 1. Reimplement `outstanding` as `self.state(agent).status not in TERMINAL` and confirm the final `outstanding(late's task) is True` fails — Critical bug 2. Change `child_tasks` to `WHERE parent_agent = ?` and confirm the same `[early, late]` assertion fails. Restore after each.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Ask the task, not the agent, and read history not the last row"
```

---

### Task 2: `collect_task` records consumption

**Files:**
- Create: `ancalagon/migrations/005_collected_status.up.sql`, `ancalagon/migrations/005_collected_status.down.sql`
- Modify: `ancalagon/bus/agent_status.py`, `ancalagon/tools/delegate/collect_task.py`, `ancalagon/bus/bus.py`
- Test: `tests/unit/test_migrations.py`, `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `Bus.outstanding` (Task 1).
- Produces: `AgentStatus.COLLECTED`, `Bus.uncollected(task: int) -> list[int]`, schema version 5.

`COLLECTED` is **not** in `TERMINAL` — it is an annotation on an already-ended agent, not an ending. Adding it to `TERMINAL` would make `outstanding`'s in-flight test wrong.

SQLite cannot alter a `CHECK`, so the migration recreates `agent_events` exactly as `004` does. Copy `004_idling_status.up.sql` and add `'collected'` to the status list. **`ALTER TABLE ... RENAME` does not rename indexes in SQLite**, so keep `004`'s `DROP INDEX agent_events_agent;` after the rename — without it the `CREATE INDEX` collides with the old table's surviving index. The `.down.sql` deletes `collected` rows before restoring the old constraint.

- [ ] **Step 1: Write the failing test**

Extend `test_migrations_round_trip_and_checks_reject_bad_rows` in `tests/unit/test_migrations.py`, which already asserts a version and rejects a bogus status:

```python
    assert latest_version() == 5
    conn.execute(
        "INSERT INTO agent_events (agent, ts, status, source) "
        "VALUES (1, 't', 'collected', 'worker')"
    )

    migrate(conn, 4)
    assert user_version(conn) == 4
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) "
            "VALUES (1, 't', 'collected', 'worker')"
        )
```

Going *down* must restore the old constraint, not merely renumber the version.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_migrations.py -v`
Expected: FAIL on `assert latest_version() == 5`.

- [ ] **Step 3: Write the migration and the status**

Add `COLLECTED = "collected"` to `AgentStatus`. Do **not** add it to `TERMINAL`. Write `005_collected_status.up.sql` and `.down.sql` on the pattern above.

- [ ] **Step 4: Write the failing tool test**

Extend the existing `collect_task` behaviour test in `tests/unit/test_tools.py`:

```python
    assert bus.uncollected(parent_task) == [child]
    got = collect.invoke(json.dumps({"task": child}), ctx)
    assert got.ok is True
    assert AgentStatus.COLLECTED in [e.status for e in bus.history(child)]
    assert bus.uncollected(parent_task) == []

    unfinished = collect.invoke(json.dumps({"task": still_running}), ctx)
    assert unfinished.ok is False
    assert AgentStatus.COLLECTED not in [e.status for e in bus.history(still_running)]
```

The last two lines matter: collecting an agent that has not settled must record nothing, or an idling child would be marked consumed and never waited for.

- [ ] **Step 5: Implement**

In `CollectTask.run`, after a successful read and only when `bus.outstanding(state.task)` is `False`, append `bus.record(args.task, AgentStatus.COLLECTED, EventSource.WORKER)`. Add to `Bus`:

```python
    def uncollected(self, task: int) -> list[int]:
        return [
            self._newest_agent(t.id)
            for t in self.child_tasks(task)
            if not self.outstanding(t.id)
            and AgentStatus.COLLECTED not in {e.status for e in self.history(self._newest_agent(t.id))}
        ]
```

- [ ] **Step 6: Verify and mutation-check**

Run the full suite. Then record `COLLECTED` unconditionally rather than only when settled, and confirm the `still_running` assertion fails. Then add `COLLECTED` to `TERMINAL` and confirm Task 1's `outstanding` test fails. Restore both.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "A parent's reading of a child's answer is a fact in the log"
```

---

### Task 3: The `Children` port

**Files:**
- Create: `ancalagon/session/children.py`, `ancalagon/session/bus_children.py`, `ancalagon/session/no_children.py`, `ancalagon/session/__init__.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `Bus.live_children`, `Bus.uncollected` (Tasks 1-2).
- Produces:

```python
class Children(typing.Protocol):
    def outstanding(self) -> tuple[int, ...]: ...
    def uncollected(self) -> tuple[int, ...]: ...
```

`BusChildren(bus: Bus, agent: int)` implements it against the run's database; `NoChildren()` is the null object returning two empty tuples, with a module-level `NO_CHILDREN = NoChildren()` singleton because Ruff's B008 forbids a call in a default argument. `UNSANDBOXED` and `UNMETERED` are the existing precedents for that shape.

This is the same seam as `Meter`: the session depends on the protocol, and the bus-backed implementation is injected by the worker. The session never opens a database.

- [ ] **Step 1: Write the failing test**

```python
def test_children_reports_outstanding_and_uncollected_for_one_agent(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    done = bus.enqueue(tmp_path / "done", parent_agent=parent)
    busy = bus.enqueue(tmp_path / "busy", parent_agent=parent)

    children = BusChildren(bus, parent)
    assert children.outstanding() == (done, busy)
    assert children.uncollected() == ()

    bus.record(done, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(done, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert children.outstanding() == (busy,)
    assert children.uncollected() == (done,)

    bus.record(done, AgentStatus.COLLECTED, EventSource.WORKER)
    assert children.uncollected() == ()

    assert NO_CHILDREN.outstanding() == ()
    assert NO_CHILDREN.uncollected() == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k children_reports -v`
Expected: FAIL with `ImportError: cannot import name 'BusChildren'`.

- [ ] **Step 3: Implement**

```python
class BusChildren(Children):
    def __init__(self, bus: Bus, agent: int):
        self.bus = bus
        self.agent = agent

    def outstanding(self) -> tuple[int, ...]:
        return tuple(s.agent for s in self.bus.live_children(self.agent))

    def uncollected(self) -> tuple[int, ...]:
        return tuple(self.bus.uncollected(self.bus.state(self.agent).task))
```

- [ ] **Step 4: Verify, mutation-check, commit**

Run the full suite. Then make `uncollected` ignore the `COLLECTED` filter and confirm the `== ()` assertion after recording it fails. Restore.

```bash
git add -A
git commit -m "A session learns about its children through a port, like it learns metering"
```

---

### Task 4: Narrowing moves into the turn loop, and `_final_turn` collapses

**Files:**
- Modify: `ancalagon/session.py`, `ancalagon/worker.py`
- Test: `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: `Children`, `NO_CHILDREN` (Task 3).
- Produces: `Session(..., children: Children = NO_CHILDREN)`; `Session._final_turn` deleted; `build_registry` no longer narrows.

**Why the collapse is required rather than tidy.** With narrowing decided once per attempt, a parent that collects its last child mid-attempt holds neither tool — `submit_answer` was withheld at attempt start, and `idle` refuses with nothing outstanding — and burns turns to a deadlock. Narrowing must therefore be re-evaluated each turn, and once it is, the last turn is an ordinary turn with two flags.

The narrowing rule, evaluated per turn:

- `idle` is declared when `children.outstanding()` is non-empty.
- `submit_answer` is declared when `outstanding()` and `uncollected()` are both empty, **or** this is the final turn.

The final turn declares `submit_answer` regardless of collection. Being cut off is not the same as choosing to skip, and the outcome is `Exhausted` either way.

- [ ] **Step 1: Write the failing test**

```python
def test_a_session_narrows_each_turn_and_the_last_turn_is_an_ordinary_one():
    children = ScriptedChildren([(2,), ()], [(), (2,)])
    llm = FakeLLM([...])
    session = Session(..., children=children, ...)

    outcome = session.run()

    assert [sorted(s.name for s in seen) for seen in llm.offered] == [
        ["collect_task", "idle", "read_file"],
        ["collect_task", "read_file"],
        ["submit_answer"],
    ]
    assert outcome.kind is OutcomeKind.EXHAUSTED
```

`ScriptedChildren` is a fake in the test file returning a scripted sequence, following the `FakeLLM` style already there. The three rows are the point: turn one has a live child so `idle` is offered and `submit_answer` is not; turn two has a settled but uncollected child so neither is offered; the final turn offers `submit_answer` alone despite the outstanding collection.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_session_loop.py -k narrows_each_turn -v`
Expected: FAIL with `TypeError: Session.__init__() got an unexpected keyword argument 'children'`.

- [ ] **Step 3: Implement**

Add `children: Children = NO_CHILDREN` to `Session.__init__`. Replace `run`'s `schemas = self.registry.schemas()` hoist with a per-turn `self._declarations(final)`, delete `_final_turn`, and fold its three behaviours into the loop's last iteration: record `FINAL_INSTRUCTION`, declare `submit_answer` only, pass `force_tool=SUBMIT`. Move its outcome parsing — `Exhausted` on a valid answer, `Failed` on one that will not validate — to after the loop.

The exhaustion branch keeps its meaning but asks the port rather than the registry:

```python
            if self.remaining.turns_exhausted and self.children.outstanding():
                return Idling(summary="turns exhausted while children ran", spent=self._spent())
```

In `worker.py`, delete the `exempt`/`excluded` narrowing from `build_registry` so it binds whatever the role allows, and pass `children=BusChildren(bus, agent_id)` when constructing the `Session`.

- [ ] **Step 4: Verify**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`

- [ ] **Step 5: Mutation-check**

Hoist the declarations back out of the loop so narrowing happens once, and confirm the three-row assertion fails. Then declare `submit_answer` on the final turn only when `uncollected()` is empty, and confirm the same test fails on the third row. Restore after each.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Narrow the tools every turn, so the last turn is not a special case"
```

---

### Task 5: The supervisor wakes an idling parent

**Files:**
- Modify: `ancalagon/bus/bus.py`, `ancalagon/supervisor/supervisor.py`, `ancalagon/tools/idle/idle.py`
- Test: `tests/unit/test_bus.py`, `tests/unit/test_supervisor.py`, `tests/integration/test_scripted_escalation.py`

**Interfaces:**
- Consumes: `Bus.child_tasks`, `Bus.outstanding` (Task 1).
- Produces: `Bus.wakeable() -> list[TaskRow]`; `Supervisor._wake_idling`.

```
wakeable = tasks T where
    'idling' in history(newest agent N of T), at event id E
    AND some C in child_tasks(T):  not outstanding(C)
                                   AND C's newest agent has an event with id > E
```

`agent_events.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, a total order over the run — no timestamps, no ties. `> E` means *settled since I last stopped*; without it a re-idled parent spins on news it has already consumed.

Idempotence is structural: once `T` is re-enqueued its newest agent is the new one, whose history holds no idling, so `T` leaves the result set. Two children settling in one tick yield one row, because the query is per task.

`Idle.run` switches from `bus.live_children` to the same source the narrowing uses, so the tool and the declaration cannot disagree.

- [ ] **Step 1: Write the failing bus test**

```python
def test_a_task_is_wakeable_only_for_news_since_it_last_idled(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    first = bus.enqueue(tmp_path / "a", parent_agent=parent)
    second = bus.enqueue(tmp_path / "b", parent_agent=parent)

    assert bus.wakeable() == []

    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(parent, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.wakeable() == []

    bus.record(first, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(first, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]

    woken = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    assert bus.wakeable() == []

    bus.record(woken, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(woken, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.wakeable() == []

    bus.record(second, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(second, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]
```

The fifth assertion is the anti-spin case: the parent has idled again, `first` is still settled, and that must **not** be news. The fourth is idempotence: once re-enqueued, the task drops out without any flag being cleared.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k wakeable -v`
Expected: FAIL with `AttributeError: 'Bus' object has no attribute 'wakeable'`.

- [ ] **Step 3: Implement `wakeable`**

Compose it in Python over the primitives from Task 1 rather than one nested SQL statement — a run holds tens of tasks, and the composition is what the next reader can check:

```python
    def wakeable(self) -> list[TaskRow]:
        return [t for t in self._all_tasks() if self._has_news(t.id)]
```

`_has_news(task)` finds the newest agent's last `idling` event id via
`SELECT MAX(id) FROM agent_events WHERE agent = ? AND status = ?`, returns `False` when there is none, and otherwise asks whether any child task is not `outstanding` and has `MAX(agent_events.id) > E`.

- [ ] **Step 4: Write the failing supervisor test**

Extend the supervisor's behaviour test with its existing fake spawner:

```python
    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)
    supervisor.tick()

    resumed = [s for s in bus.live() if s.dir == str(parent_dir)]
    assert len(resumed) == 1
    assert resumed[0].agent != parent

    supervisor.tick()
    assert len([s for s in bus.live() if s.dir == str(parent_dir)]) == 1
```

The second `tick` is the double-enqueue guard: a second pass must not add another agent.

- [ ] **Step 5: Implement the wake**

Append `self._wake_idling()` to `tick`, which becomes `self._start_queued(); self._reap(); self._wake_idling()`. No existing step moves. `_wake_idling` enqueues `pathlib.Path(t.dir)` for each `t in self.bus.wakeable()`, with `parent_agent=self.bus.task(pathlib.Path(t.dir)).parent_agent` so the row's own parent is preserved.

Because the wake runs at the *end* of the tick, `run_until_idle`'s existing `queued_count() == 0` check sees it on the next line. **`run_until_idle` does not change.** `shutdown` wakes nothing, because it does not schedule.

- [ ] **Step 6: Point `Idle` at the same source**

`Idle.run` calls `bus.outstanding` over `bus.child_tasks` of its own task rather than `bus.live_children(self.agent)`, so the refusal and the declaration cannot disagree.

- [ ] **Step 7: Prove it end to end**

Extend `tests/integration/test_scripted_escalation.py` so its scripted root delegates, idles, and is resumed after the child completes — through real worker subprocesses. Assert the root's task directory holds two agents and that the second one's transcript contains the first's messages. A green unit test proves a row was written; only this proves the loop.

- [ ] **Step 8: Verify and mutation-check**

Run both suites. Then drop the `> E` comparison so any settled child is news, and confirm the anti-spin assertion fails. Then remove the enqueue guard and confirm the second `tick` adds a second agent. Restore after each.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "A child settling since its parent stopped is what wakes the parent"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Read both documents end to end before editing**

A grep finds dead identifiers; it cannot find a true-sounding sentence describing behaviour that no longer exists. Both documents describe `check_task` as how a parent learns anything.

- [ ] **Step 2: Write what changed**

Cover: `idle` and when it is offered; that `submit_answer` is withheld until every child is both settled **and collected**, so a parent cannot finish without reading what it commissioned; that an idling attempt ends and resumes as a new agent against the same task; that **a role's `budget` is granted per attempt, so a parent with three children may consume four budgets**; that schema version 5 means existing run databases need `ancalagon migrate`; and that a downgrade past 5 or 4 deletes `collected` and `idling` rows, so a parent mid-idle loses the record of why it stopped.

- [ ] **Step 3: Grep for what you missed**

```bash
grep -rn "resumable_idle\|latest_agent\|_final_turn\|live_children" README.md docs/
```

Expected: no matches outside `docs/superpowers/`, which is immutable and records history.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Document idling, collection, and the budget they cost"
```

---

## Self-Review

**Spec coverage.** The one primitive → Task 1. Children resolve through the task → Task 1. Both Critical bugs → Task 1, with a mutation check each. Consumption recorded → Task 2. Narrowing per turn behind a port → Tasks 3-4. `_final_turn` collapsed → Task 4. Wake predicate and `tick` → Task 5. `run_until_idle` unchanged → Task 5, asserted by the absence of a change. Deletions → Tasks 1 and 4. Budget-per-attempt and the migration → Task 6.

**Two things left for the implementer to settle, flagged rather than guessed:**

1. Whether `_wake_idling` needs its own guard against re-enqueuing a task that is already queued (Task 5, Step 5). The predicate should exclude it — a queued task's newest agent has no `idling` in its history — but the second `tick` assertion is there to prove it rather than assume it. If the assertion fails, the guard is real and belongs in `_wake_idling`.
2. Whether `wakeable` needs `_all_tasks()` as a new query or can reuse an existing one (Task 5, Step 3). `Bus` has no "every task" reader today.

**Known and accepted, from the spec:** budget is granted per attempt, so a parent with three children may consume four; `run_until_idle` still returns past queued work on the orphans path; `collected` records that a parent read an answer, not that it used it.

**Type consistency.** `Bus.child_tasks(task: int) -> list[TaskRow]`, `Bus.outstanding(task: int) -> bool`, `Bus.uncollected(task: int) -> list[int]`, `Bus.wakeable() -> list[TaskRow]`, `Bus.live_children(agent: int) -> list[AgentState]`, `Children.outstanding() -> tuple[int, ...]`, `Children.uncollected() -> tuple[int, ...]`, `BusChildren(bus, agent)`, `NO_CHILDREN` are used identically in every task that mentions them.
