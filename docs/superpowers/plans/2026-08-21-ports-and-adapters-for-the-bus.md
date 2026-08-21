# Ports and Adapters for the Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `Bus` into two adapters that only touch the database, move every domain predicate into a pure package that takes a snapshot, and machine-check that domain never imports an adapter and SQL never leaves one.

**Architecture:** `Bus.snapshot()` loads all tasks, agents and events in three queries and folds each agent's attempt once, into a frozen `Snapshot` in `contracts`. Every predicate becomes a pure function of that value in `ancalagon/schedule/`. Orchestrators load a snapshot, then decide. `Bus` splits into `LifecycleStore` (tasks, agents, agent_events) and `MeterStore` (model_calls) sharing one connection.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy Core as a query builder only, SQLite via stdlib `sqlite3`, pytest, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-21-ports-and-adapters-for-the-bus-design.md`

## Global Constraints

- Pyright strict, **zero errors**. `Any` banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and hand-rolled recursive JSON types banned for the same reason.
- Every generic parameterised. `Sequence`/`Mapping` from `collections.abc` for parameters that are not mutated.
- **No comments** except a one-line header on a class or module. No docstrings, no TODOs.
- All Pydantic models `frozen=True`. **One class per file**, and this codebase's established pattern is **one function per file** for pure functions — see `attempt_of.py`, `depth_of.py`.
- Fully qualified imports, no relative imports. A class implementing a `Protocol` **inherits** it, except `Process`, which is `subprocess.Popen`'s shape.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance` on our own types, no bare `except`, no workaround guards.
- **Never ask an agent's LATEST status what happened to it.** Fold the history. This defect has shipped five times in this area.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file. Concrete assertions, never `assert x is not None`.
- **No mocking.** `unittest.mock` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, `FakeProcess`, `FakeSpawner`, `FakeLiveness`.
- **SQLAlchemy is a query builder only.** No ORM, no `Engine`, no session. Execution stays on the stdlib `sqlite3` connection. `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` stay raw — the write-lock timing is depended upon and a leaked lock there was fixed this week.
- Migrations stay raw SQL in `001_init.up.sql`, applied as they are now. `001_init` is the only migration and is edited in place if ever needed; run directories are disposable.
- **There is no bypass.** The pre-commit skip flag and `git commit -n` are blocked by a `PreToolUse` hook. If a hook fails, fix the cause or stop and raise it. **Never `git stash`.**
- `python-fp-lint` lints the whole staged content of any file you touch. Excluded: `tests/`, `supervisor/process.py`, `supervisor/adopted_process.py`, `cli.py`, `worker.py`. Everything else is linted.
- **No behaviour changes anywhere in this plan.** Record the test counts before each task; they must be identical after, except where a task explicitly adds a test. If an existing expectation needs changing, STOP and report it — that means a query moved.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`.
- Never reference an external codebase in a tracked artifact.

---

## File Structure

**Created**
- `ancalagon/contracts/harness_task.py` — `HarnessTask`, moved from `bus/task_row.py` and renamed.
- `ancalagon/contracts/snapshot.py` — `Snapshot`, the frozen value every predicate reads.
- `ancalagon/schedule/` — one pure function per file: `newest_agent.py`, `task_of.py`, `outstanding.py`, `uncollected.py`, `live_children.py`, `active_for.py`, `unreaped.py`, `is_news.py`, `has_news.py`, `wakeable.py`, `depth_of.py`.
- `ancalagon/bus/meter_store.py` — `MeterStore`, owning `model_calls`.
- `ancalagon/bus/connect.py` — opens the connection, applies pragmas, checks the schema version.

**Modified**
- `ancalagon/bus/bus.py` — loses every domain method, gains `snapshot()`, is renamed `LifecycleStore`.
- `ancalagon/supervisor/supervisor.py`, `ancalagon/children/bus_children.py`, `ancalagon/tools/delegate/*.py`, `ancalagon/tools/idle/idle.py`, `ancalagon/answer.py`, `ancalagon/cli.py`, `ancalagon/worker.py` — fetch a snapshot, then call `schedule`.
- `pyproject.toml` — three import-linter contracts.
- `README.md`, `docs/architecture.md`.

**Deleted**
- `ancalagon/bus/task_row.py`, `ancalagon/bus/depth_of.py`, and — pending Task 7 — `ancalagon/bus/agent_state.py`.

---

### Task 1: `HarnessTask`

**Files:**
- Create: `ancalagon/contracts/harness_task.py`
- Delete: `ancalagon/bus/task_row.py`
- Modify: every importer of `TaskRow`

**Interfaces:**
- Produces: `HarnessTask` with fields `id: int`, `dir: str`, `parent_agent: int`, `created: str`.

A pure mechanical move and rename, done first so later tasks import the final name. `Row` names a row of a table; once the pure functions reason about it, that storage name is the same leak as a SQL fragment travelling as a string.

- [ ] **Step 1: Move the file**

Create `ancalagon/contracts/harness_task.py`:

```python
# A unit of work, identified by its directory; agents are attempts at it.
import pydantic


class HarnessTask(pydantic.BaseModel, frozen=True):
    id: int
    dir: str
    parent_agent: int
    created: str
```

Delete `ancalagon/bus/task_row.py`.

- [ ] **Step 2: Rewrite every importer**

```bash
grep -rn "TaskRow" ancalagon tests | grep -v __pycache__
```

Rewrite each to `from ancalagon.contracts.harness_task import HarnessTask` and the symbol to `HarnessTask`. Then grep for the old name as TEXT — a rename Pyright accepts can still leave string literals behind.

- [ ] **Step 3: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "A task is a harness task, not a row"
```

Test counts must be unchanged.

---

### Task 2: `Snapshot` and `Bus.snapshot()`

**Files:**
- Create: `ancalagon/contracts/snapshot.py`
- Modify: `ancalagon/bus/bus.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `HarnessTask` (Task 1), `AgentEvent`, `Attempt`, `attempt_of`.
- Produces: `Snapshot` with `tasks`, `agents_by_task`, `task_by_agent`, `events`, `attempts`; and `Bus.snapshot() -> Snapshot`.

Purely additive — nothing consumes it yet, so the suite stays green.

- [ ] **Step 1: Write the model**

```python
# ancalagon/contracts/snapshot.py
# Everything about a run's lifecycle state, read once and folded once.
from collections.abc import Mapping

import pydantic

from ancalagon.attempt.attempt import Attempt
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.harness_task import HarnessTask


class Snapshot(pydantic.BaseModel, frozen=True):
    tasks: tuple[HarnessTask, ...]
    agents_by_task: Mapping[int, tuple[int, ...]]
    task_by_agent: Mapping[int, int]
    events: Mapping[int, tuple[AgentEvent, ...]]
    attempts: Mapping[int, Attempt]
```

`agents_by_task` is ordered by agent id, so the newest is last. `attempts` is folded from `events` at construction — derived data inside one immutable value, not a second source of truth.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/test_bus.py`:

```python
def test_a_snapshot_carries_every_task_agent_and_folded_attempt(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    first = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    settle(bus, first, AgentStatus.COMPLETED)
    second = bus.enqueue(tmp_path / "child", parent_agent=first)

    snap = bus.snapshot()

    assert [t.dir for t in snap.tasks] == [str(tmp_path / "root"), str(tmp_path / "child")]
    assert snap.agents_by_task == {1: (first,), 2: (second,)}
    assert snap.task_by_agent == {first: 1, second: 2}
    assert snap.attempts[first] == Closed(verdict=AgentStatus.COMPLETED)
    assert snap.attempts[second] == Queued()
    assert [e.status for e in snap.events[second]] == [AgentStatus.QUEUED]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k snapshot -v`
Expected: FAIL with `AttributeError: 'Bus' object has no attribute 'snapshot'`

- [ ] **Step 4: Build it in three queries**

Add module-level statements beside the existing ones and a `snapshot` method. Three reads — all tasks ordered by id, all agents ordered by id, all events ordered by id — then group in memory:

```python
    def snapshot(self) -> Snapshot:
        tasks = tuple(
            HarnessTask.model_validate(dict(r)) for r in self._exec(_ALL_TASKS).fetchall()
        )
        agent_rows = [dict(r) for r in self._exec(_ALL_AGENTS).fetchall()]
        event_rows = [AgentEvent.model_validate(dict(r)) for r in self._exec(_ALL_EVENTS).fetchall()]
        agents_by_task = {
            task.id: tuple(int(r["id"]) for r in agent_rows if int(r["task"]) == task.id)
            for task in tasks
        }
        task_by_agent = {int(r["id"]): int(r["task"]) for r in agent_rows}
        events = {
            int(r["id"]): tuple(e for e in event_rows if e.agent == int(r["id"]))
            for r in agent_rows
        }
        return Snapshot(
            tasks=tasks,
            agents_by_task=agents_by_task,
            task_by_agent=task_by_agent,
            events=events,
            attempts={agent: attempt_of(found) for agent, found in events.items()},
        )
```

The grouping is quadratic in rows. That is fine at these sizes and keeps it one readable expression; if it ever matters, group with a single pass. Do not optimise it now.

- [ ] **Step 5: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The bus can hand over everything at once"
```

---

### Task 3: The pure `schedule` package

**Files:**
- Create: `ancalagon/schedule/` — eleven files, one function each
- Test: `tests/unit/test_schedule.py`

**Interfaces:**
- Consumes: `Snapshot` (Task 2), the `Attempt` states.
- Produces, all taking `snapshot: Snapshot` as their first parameter:
  - `newest_agent(snapshot, task: int) -> int`
  - `task_of(snapshot, agent: int) -> HarnessTask`
  - `outstanding(snapshot, task: int) -> bool`
  - `uncollected(snapshot, task: int) -> tuple[int, ...]`
  - `live_children(snapshot, agent: int) -> tuple[int, ...]`
  - `active_for(snapshot, dir: str) -> tuple[int, ...]`
  - `unreaped(snapshot) -> tuple[int, ...]`
  - `is_news(snapshot, agent: int) -> bool`
  - `has_news(snapshot, task: int) -> bool`
  - `wakeable(snapshot) -> tuple[HarnessTask, ...]`
  - `depth_of(snapshot, agent: int) -> int`

Additive — nothing calls them yet. This is where the scheduling rules become readable, so write them as direct translations of the current methods, not as improvements.

**These return agent ids where the old methods returned `AgentState`.** That is deliberate: it is what lets `AgentState` be deleted in Task 7. A caller wanting a directory uses `task_of`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_schedule.py`. Build `Snapshot` values directly — these are pure functions and need no database:

```python
def _snapshot(
    tasks: Sequence[tuple[int, str, int]],
    agents: Sequence[tuple[int, int]],
    events: Mapping[int, Sequence[tuple[int, AgentStatus, EventSource]]],
) -> Snapshot:
    built = {
        agent: tuple(
            AgentEvent(id=i, agent=agent, ts="t", status=s, source=src, pid=0, summary="")
            for i, s, src in rows
        )
        for agent, rows in events.items()
    }
    return Snapshot(
        tasks=tuple(HarnessTask(id=i, dir=d, parent_agent=p, created="t") for i, d, p in tasks),
        agents_by_task={
            t: tuple(a for a, owner in agents if owner == t) for t, _, _ in tasks
        },
        task_by_agent={a: t for a, t in agents},
        events=built,
        attempts={agent: attempt_of(found) for agent, found in built.items()},
    )


def test_the_scheduling_rules_read_a_snapshot():
    W, S = EventSource.WORKER, EventSource.SUPERVISOR
    snap = _snapshot(
        tasks=[(1, "/root", 0), (2, "/child", 1)],
        agents=[(1, 1), (2, 2)],
        events={
            1: [(1, AgentStatus.QUEUED, S), (2, AgentStatus.CLAIMED, S),
                (3, AgentStatus.RUNNING, S), (4, AgentStatus.IDLING, S)],
            2: [(5, AgentStatus.QUEUED, S), (6, AgentStatus.CLAIMED, S),
                (7, AgentStatus.RUNNING, S), (8, AgentStatus.COMPLETED, S)],
        },
    )

    assert newest_agent(snap, 1) == 1
    assert task_of(snap, 2).dir == "/child"
    assert outstanding(snap, 1) is True
    assert outstanding(snap, 2) is False
    assert uncollected(snap, 1) == (2,)
    assert live_children(snap, 1) == ()
    assert active_for(snap, "/child") == ()
    assert unreaped(snap) == ()
    assert is_news(snap, 2) is True
    assert has_news(snap, 1) is True
    assert [t.dir for t in wakeable(snap)] == ["/root"]
    assert depth_of(snap, 2) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_schedule.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.schedule'`

- [ ] **Step 3: Write the functions**

Translate each from `bus.py`. The three with real content:

```python
# ancalagon/schedule/outstanding.py
# Whether a task still has work in flight, counting an idled parent as outstanding.
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.collected import Collected
from ancalagon.attempt.lost import Lost
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.snapshot import Snapshot
from ancalagon.schedule.newest_agent import newest_agent


def outstanding(snapshot: Snapshot, task: int) -> bool:
    match snapshot.attempts[newest_agent(snapshot, task)]:
        case Closed(verdict=closed_verdict):
            return closed_verdict is AgentStatus.IDLING
        case Collected(verdict=collected_verdict):
            return collected_verdict is AgentStatus.IDLING
        case Lost():
            return False
        case _:
            return True
```

```python
# ancalagon/schedule/has_news.py
# Whether a task's child has settled since that task's newest agent idled.
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.snapshot import Snapshot
from ancalagon.schedule.is_news import is_news
from ancalagon.schedule.newest_agent import newest_agent


def has_news(snapshot: Snapshot, task: int) -> bool:
    parent = newest_agent(snapshot, task)
    idled = [e.id for e in snapshot.events[parent] if e.status is AgentStatus.IDLING]
    if not idled:
        return False
    return any(
        is_news(snapshot, newest_agent(snapshot, child.id))
        and snapshot.events[newest_agent(snapshot, child.id)][-1].id > idled[-1]
        for child in snapshot.tasks
        if child.parent_agent in snapshot.agents_by_task[task]
    )
```

```python
# ancalagon/schedule/depth_of.py
# Counts an agent's ancestors, with the root at zero, so max_depth can bound nesting.
from ancalagon.contracts.snapshot import Snapshot
from ancalagon.schedule.task_of import task_of

MAX_HOPS = 64


def depth_of(snapshot: Snapshot, agent: int) -> int:
    depth = 0
    current = task_of(snapshot, agent).parent_agent
    while current != 0:
        if depth >= MAX_HOPS:
            raise ValueError(f"agent {agent} exceeds {MAX_HOPS} ancestors; parent chain is cyclic")
        current = task_of(snapshot, current).parent_agent
        depth += 1
    return depth
```

`newest_agent` is `snapshot.agents_by_task[task][-1]`. `task_of` looks up `task_by_agent` then finds the task. `uncollected`, `live_children`, `active_for`, `unreaped`, `is_news` and `wakeable` are direct translations of the existing methods — read each from `bus.py` and change only where the data comes from.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The scheduling rules are functions of a snapshot"
```

---

### Task 4: The supervisor fetches, then decides

**Files:**
- Modify: `ancalagon/supervisor/supervisor.py`
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: `Bus.snapshot()` (Task 2), `schedule` (Task 3).

`Bus` keeps its domain methods through Tasks 4-6 so each stays green; Task 7 deletes them once nothing calls them.

- [ ] **Step 1: Load one snapshot per tick**

`tick` takes a snapshot once and passes it to the three phases:

```python
    def tick(self) -> None:
        snapshot = self.bus.snapshot()
        self._start_queued(snapshot)
        self._reap()
        self._wake_idling(snapshot)
```

`_reap` reads no lifecycle state — it polls processes — so it takes nothing.

`_wake_idling` becomes:

```python
    def _wake_idling(self, snapshot: Snapshot) -> None:
        asleep = [
            task
            for task in wakeable(snapshot)
            if newest_agent(snapshot, task.id) not in self.live
        ]
        for task in asleep:
            self.bus.enqueue(pathlib.Path(task.dir), parent_agent=task.parent_agent)
    ```

`resolve_stale` takes its own snapshot — it runs once at startup, before the loop.

- [ ] **Step 2: Run the suite**

Run: `uv run python -m pytest tests/unit tests/integration -q`
Expected: PASS, counts unchanged. A failure here means a predicate was translated wrongly in Task 3, not that a test needs changing.

- [ ] **Step 3: Prove the N+1 is gone**

Add to `tests/unit/test_supervisor.py` a test that counts queries across one tick. Wrap the connection's `execute` by subclassing nothing — instead assert on a real count using `sqlite3`'s trace callback:

```python
def test_a_tick_reads_the_database_a_fixed_number_of_times(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    for name in ("a", "b", "c", "d"):
        bus.enqueue(tmp_path / name, parent_agent=parent)

    statements: list[str] = []
    bus.conn.set_trace_callback(statements.append)
    Supervisor(
        bus=bus, spawner=FakeSpawner([]), max_concurrent=0, timeout_s=60, clock=FakeClock()
    ).tick()
    bus.conn.set_trace_callback(None)

    assert len(statements) == 3
```

`max_concurrent=0` keeps `_start_queued` from spawning, so the count is the snapshot's three reads and nothing else. Before this task the same tick issues one read per task plus three per child.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The supervisor reads once a tick"
```

---

### Task 5: The tools fetch, then decide

**Files:**
- Modify: `ancalagon/tools/delegate/collect_task.py`, `check_task.py`, `delegate_to.py`, `ancalagon/tools/idle/idle.py`, `ancalagon/children/bus_children.py`
- Delete: `ancalagon/bus/depth_of.py`
- Test: `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `Bus.snapshot()`, `schedule`.

Each tool opens a `Bus`, takes a snapshot, and calls `schedule`. `delegate_to` uses `schedule.depth_of` — delete `ancalagon/bus/depth_of.py` and rewrite its importers.

`BusChildren` takes a snapshot per call, since a session asks between turns and the answer must be current:

```python
    def outstanding(self) -> tuple[int, ...]:
        snapshot = self.bus.snapshot()
        return live_children(snapshot, self.agent)

    def uncollected(self) -> tuple[int, ...]:
        snapshot = self.bus.snapshot()
        return uncollected(snapshot, snapshot.task_by_agent[self.agent])
```

- [ ] **Step 1: Rewrite each caller**

```bash
grep -rn "bus\.\(outstanding\|uncollected\|live_children\|active_for\|newest_agent\|attempt\)" ancalagon/tools ancalagon/children
```

Rewrite each to take a snapshot and call the pure function. `collect_task` already computes `newest`; it becomes `newest_agent(snapshot, task)`.

- [ ] **Step 2: Run the suite**

Run: `uv run python -m pytest tests/unit tests/integration -q`
Expected: PASS, counts unchanged.

- [ ] **Step 3: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The tools read a snapshot"
```

---

### Task 6: `answer`, `cli` and `worker` fetch, then decide

**Files:**
- Modify: `ancalagon/answer.py`, `ancalagon/answer_command.py`, `ancalagon/cli.py`, `ancalagon/worker.py`
- Test: `tests/unit/test_answer.py`

**Interfaces:**
- Consumes: `Bus.snapshot()`, `schedule`.

The same move for the remaining three orchestrators. `cli.main` uses `newest_agent` to find the root's outcome file; `answer` uses `active_for`; `worker` uses `depth_of`.

- [ ] **Step 1: Rewrite each caller, run the suite, commit**

```bash
grep -rn "bus\.\(active_for\|newest_agent\|state\)" ancalagon/answer.py ancalagon/answer_command.py ancalagon/cli.py ancalagon/worker.py
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The remaining orchestrators read a snapshot"
```

Counts unchanged.

---

### Task 7: `Bus` loses its domain methods, and `AgentState` goes

**Files:**
- Modify: `ancalagon/bus/bus.py`
- Delete: `ancalagon/bus/agent_state.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: Tasks 4-6, which removed every caller.

- [ ] **Step 1: Delete the domain methods**

Remove `outstanding`, `uncollected`, `live_children`, `active_for`, `unreaped`, `wakeable`, `newest_agent`, `queued_count`, `attempt`, `_is_news`, `_has_news`, `_last_idled_event_id`, `_newest_event_id`, `_all_tasks`, `child_tasks` and `state`, along with any statement constant only they used.

`Bus` should be left with `open`, `snapshot`, `record`, `_record`, `enqueue`, `claim`, `_queued`, `history`, `task`, `record_call`, `calls`, `tokens_by_agent`, `_exec`, `_states`, `_now`, `_connect`.

**`_queued` and `claim` keep their fold check.** `claim` runs inside its own transaction and must not depend on a snapshot taken before it.

- [ ] **Step 2: Delete `AgentState` or record why not**

Its three users were `bus.py`, `supervisor.py` and `collect_task.py`, all of which now read `attempts` and `events`. Delete `ancalagon/bus/agent_state.py`.

If a caller genuinely still needs it, **stop and report which and why** rather than keeping it silently — the spec expects deletion.

- [ ] **Step 3: Grep for stragglers**

```bash
grep -rn "AgentState\|TaskRow\|bus.outstanding\|bus.wakeable\|bus.newest_agent" ancalagon tests | grep -v __pycache__
```

Expected: nothing.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "The bus holds no rules"
```

---

### Task 8: Two adapters over one connection

**Files:**
- Create: `ancalagon/bus/connect.py`, `ancalagon/bus/meter_store.py`
- Modify: `ancalagon/bus/bus.py` (renamed `LifecycleStore`), `ancalagon/bus/bus_meter.py`, every constructor site
- Test: `tests/unit/test_metering.py`

**Interfaces:**
- Produces: `connect(path: pathlib.Path) -> sqlite3.Connection`; `LifecycleStore(conn, clock)`; `MeterStore(conn, clock)`.

- [ ] **Step 1: Extract the opener**

`connect.py` holds what `Bus._connect` and `Bus.open` do now — pragmas, row factory, and the schema-version check that raises when the database is not current. Both stores take an already-open connection.

- [ ] **Step 2: Split out `MeterStore`**

`record_call`, `calls` and `tokens_by_agent` move to `meter_store.py`, with the `model_calls` statements. `BusMeter` takes a `MeterStore` instead of a `Bus` and keeps implementing the existing `Meter` port.

- [ ] **Step 3: Rename `Bus` to `LifecycleStore`**

Rename the class and the module (`bus.py` → `lifecycle_store.py`), and rewrite every importer. Grep for `Bus` as TEXT afterwards — a rename Pyright accepts leaves string literals behind.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "Two stores, one connection"
```

---

### Task 9: Machine-check the constraints

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: the package layout from Tasks 1-8.

Two mechanics are already verified against this repository — use them, do not re-derive:

- Forbidding an external package requires `include_external_packages = True` under `[tool.importlinter]`. Without it the contract silently passes.
- `forbidden` follows indirect chains by default, so a contract on `sqlalchemy` flags `supervisor → lifecycle_store → sqlalchemy` — true of every orchestrator and not the intent. `allow_indirect_imports = True` restricts it to direct imports.

- [ ] **Step 1: Add the two forbidden contracts**

```toml
[[tool.importlinter.contracts]]
name = "Domain does not import adapters"
type = "forbidden"
source_modules = ["ancalagon.attempt", "ancalagon.schedule"]
forbidden_modules = ["ancalagon.bus"]

[[tool.importlinter.contracts]]
name = "SQL stays in the adapters"
type = "forbidden"
allow_indirect_imports = true
source_modules = [
    "ancalagon.attempt",
    "ancalagon.schedule",
    "ancalagon.supervisor",
    "ancalagon.tools",
    "ancalagon.children",
    "ancalagon.session",
    "ancalagon.llm",
    "ancalagon.contracts",
]
forbidden_modules = ["sqlite3", "sqlalchemy"]
```

Set `include_external_packages = true` under `[tool.importlinter]`. Update the existing layers contract for `ancalagon.schedule`.

- [ ] **Step 2: Prove each contract catches what it claims**

A contract that cannot fail is not protection. For EACH of the two:

- Add an import that violates it — `import sqlite3` at the top of a `schedule` module; `from ancalagon.bus...` in an `attempt` module.
- Run `uv run lint-imports` and confirm it reports that contract BROKEN, naming that module.
- Remove the import and confirm it returns to KEPT.

Report the exact output you saw for each. If a contract stays KEPT with the violation in place, it is misconfigured — fix it, do not report it as passing.

- [ ] **Step 3: Commit**

```bash
uv run lint-imports
git add -A
git commit -m "The architecture is checked, not assumed"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Read both end to end before editing**

A grep finds a dead identifier; it cannot find a true-sounding sentence describing behaviour that no longer exists. `docs/architecture.md` describes `Bus` as one object holding the queue and the log, and walks a tick through per-child reads.

- [ ] **Step 2: Write what is true**

Cover: two stores over one connection, split by domain; `snapshot()` as the only way to read lifecycle state; the scheduling rules as pure functions in `ancalagon/schedule/`; that a tick reads three times regardless of how many children exist; that `record` keeps the gate at the write; and that the three import contracts fail the build rather than a review.

Keep "It never retries. A crash is reported; the parent decides." — check it, it is still true.

- [ ] **Step 3: Grep, verify, commit**

```bash
grep -rn "Bus\|TaskRow\|AgentState\|queued_count" README.md docs/architecture.md
uv run python -m pytest tests/unit -q
git add -A
git commit -m "Document the split"
```

`git diff --stat` must show only the two documents. Report every surviving grep match and why you kept it.

---

## Self-Review

**Spec coverage.** `HarnessTask` → Task 1. `Snapshot` and `snapshot()` → Task 2. Pure `schedule` package → Task 3. Orchestrators fetch-then-decide → Tasks 4, 5, 6. `Bus` loses its rules and `AgentState` goes → Task 7. Two adapters over one shared connection → Task 8. The three contracts, with the two verified mechanics → Task 9. Docs → Task 10. `record` keeping the gate → unchanged by every task, stated in Task 7's surviving-method list.

**Ordering.** Task 1 first so later tasks import the final name. Tasks 2 and 3 are additive and independently green. Tasks 4-6 migrate callers while `Bus` still has its methods, so each is green alone. Task 7 deletes only once nothing calls them. Task 8 renames after the surface is final, so the rename is mechanical. Task 9 lands on the final layout.

**The N+1 is proved, not asserted.** Task 4 Step 3 counts statements across a tick with `sqlite3`'s trace callback and asserts exactly three. That number is the whole point of the design, so it is pinned by a test rather than left to inspection.

**Type consistency.** Every `schedule` function takes `snapshot: Snapshot` first. `newest_agent`, `depth_of` return `int`; `outstanding`, `is_news`, `has_news` return `bool`; `uncollected`, `live_children`, `active_for`, `unreaped` return `tuple[int, ...]`; `wakeable` returns `tuple[HarnessTask, ...]`; `task_of` returns `HarnessTask`. `Snapshot`'s fields are named identically in Tasks 2, 3 and 5.

**Known and accepted, from the spec:** the snapshot reads the whole event log per tick, and incremental refresh is deliberately not built; the two stores share a connection, so their transactional independence rests on inspection; `record` still issues its own read to fold the current attempt.
