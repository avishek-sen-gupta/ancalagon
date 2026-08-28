# Waking an Idling Parent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A parent that idles waiting for a child is woken when that child settles, even if the child settles before the supervisor has reaped the parent.

**Architecture:** `has_news` currently compares a child's newest event id against the parent's `IDLING` event id, but that event is written when the supervisor *reaps* the parent, not when the parent decided to idle — so a child settling in between is invisible and its parent waits forever, silently. The `idle` tool already takes a bus snapshot to compute `live_children`; it records the largest event id in that snapshot as a watermark, which travels through the outcome file onto the event, and `has_news` compares against that instead.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy Core over SQLite, pytest, uv, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-28-waking-an-idling-parent-design.md`

## Global Constraints

Copied from `CLAUDE.md` and the project guidelines. Every task's requirements include these.

- Python 3.13+; every command runs under `uv run`.
- Pyright strict, zero errors. `Any` is banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` is banned as an annotation.
- **No bare collection types and no bare generics.** Every generic is parameterised.
- **No comments.** The only permitted comment is a one-line header at the top of a module stating its purpose. No docstrings, no inline explanations, no section dividers, no TODOs.
- Dataclasses `frozen=True`; Pydantic models declared `frozen=True`. One class per file. Fully qualified imports, never relative. No static methods.
- Functional style: comprehensions over mutating loops, early return, small composable functions.
- No defensive programming: no `is not None` checks that mask bugs, no generic exception handling, no `None` defaults, no `None` returns from non-`None` return types.
- **Do not encode information in string representations.** The watermark is an integer column, never a string.
- **Text is a boundary, never a carrier.** `model_validate_json` on arrival, `model_dump_json` at the file write, nothing in between.
- No `unittest.mock`. Concrete assertions — `assert result == 30`, never `assert x is not None`.
- **Assertions are sacred.** Do not remove or weaken an existing assertion.
- SQL stays in the adapters — `ancalagon.bus` only. The import contracts in `pyproject.toml` must still report seven kept.
- Verification before every commit: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`.
- A pre-commit hook also runs `python-fp-lint` (bans `list.insert()` and subscript mutation), Talisman, and a terminology guard. If `python-fp-lint` rejects code this plan gives literally, rewrite it in the codebase's own idiom (`match`/`case` is used for this elsewhere), keep behaviour identical, and say so in the report. If Talisman flags a false positive, append to `.talismanrc` with the checksum Talisman itself reports — never one from `shasum`.

---

## File Structure

**Task 1 — carry the watermark (changes no behaviour)**

| File | Responsibility |
|---|---|
| Create `ancalagon/migrations/002_seen_through.up.sql` / `.down.sql` | One integer column on `agent_events` |
| Modify `ancalagon/bus/schema.py` | The column in the SQLAlchemy table |
| Modify `ancalagon/bus/lifecycle_store.py` | `_INSERT_EVENT` binds it; `record`/`_record` take it |
| Modify `ancalagon/contracts/agent_event.py` | `seen_through: int = 0` |
| Modify `ancalagon/contracts/idled.py`, `ancalagon/contracts/idling.py` | The tool payload and the outcome carry it |
| Modify `ancalagon/contracts/outcome_header.py` | `seen_through: int = 0`, so `_close` can read it |
| Modify `ancalagon/tools/idle/idle.py` | Reads the watermark from the snapshot it already takes |
| Modify `ancalagon/children/children.py`, `ancalagon/children/bus_children.py` | `seen_through()`, for the idling path that never calls the tool |
| Modify `ancalagon/session.py:228,320-322` | Both idling paths carry a watermark |
| Modify `ancalagon/supervisor/supervisor.py` | `_close` threads it onto the event |
| Test `tests/unit/test_supervisor.py` | The watermark survives the round trip |

**Task 2 — compare against it (fixes the bug)**

| File | Responsibility |
|---|---|
| Modify `ancalagon/schedule/has_news.py` | Anchor on `seen_through`; `max(idled)` goes |
| Test `tests/unit/test_supervisor.py` | Both reap orders, the stale child, the nested parent |

---

### Task 1: Carry the watermark

Nothing changes behaviour in this task. `has_news` still compares against the reap-time event id, so the suite must stay green throughout — that is the point of splitting it out.

**Files:**
- Create: `ancalagon/migrations/002_seen_through.up.sql`, `ancalagon/migrations/002_seen_through.down.sql`
- Modify: `ancalagon/bus/schema.py:23-33`, `ancalagon/bus/lifecycle_store.py:65-72,142-156,120-140`
- Modify: `ancalagon/contracts/agent_event.py`, `ancalagon/contracts/idled.py`, `ancalagon/contracts/idling.py`, `ancalagon/contracts/outcome_header.py`
- Modify: `ancalagon/tools/idle/idle.py`, `ancalagon/session.py:228`, `ancalagon/supervisor/supervisor.py:79-84`
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Produces: `AgentEvent.seen_through: int` (default 0), `Idled.seen_through: int` (required), `Idling.seen_through: int` (required), `OutcomeHeader.seen_through: int` (default 0).
- Produces: `LifecycleStore.record(agent, status, source, pid=0, summary="", seen_through=0) -> None`.
- Task 2 reads `AgentEvent.seen_through` off the snapshot and nothing else.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_supervisor.py`. This asserts the whole path in one behaviour — the tool computes a watermark, the outcome carries it, the supervisor records it, and the event reports it:

```python
def test_an_idle_records_how_much_of_the_log_the_parent_had_seen(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(tmp_path / "bus.db", SystemClock(), RealFileSystem())
    parent_dir = tmp_path / "tasks" / "parent"
    parent = bus.enqueue(parent_dir, parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=parent)
    bus.record(parent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(parent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    bus.record(child, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(child, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)

    highest = max(e.id for events in bus.snapshot().events.values() for e in events)
    tool = Idle(run_dir=tmp_path, agent=parent, clock=SystemClock(), fs=RealFileSystem())
    result = tool.run(IdleArgs(), _ctx(tmp_path))

    assert result.ok is True
    assert isinstance(result.summary, Idled)
    assert result.summary.waiting_for == (child,)
    assert result.summary.seen_through == highest

    parent_dir.mkdir(parents=True, exist_ok=True)
    (parent_dir / f"outcome-{parent}.json").write_text(
        Idling(
            summary=result.summary.text_for_model(),
            spent=Budget(turns=1, tool_calls=1),
            seen_through=result.summary.seen_through,
        ).model_dump_json()
    )
    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=1,
        timeout_s=5,
        poll_s=1.0,
        clock=FakeClock(),
        fs=RealFileSystem(),
    )._close(parent, AgentStatus.CRASHED, "unused")

    idled = [e for e in bus.snapshot().events[parent] if e.status is AgentStatus.IDLING]
    assert [e.seen_through for e in idled] == [highest]
```

`_ctx` and `FakeSpawner` already exist in that file. Add `Idle`, `IdleArgs`, `Idled`, `Idling`, `AgentStatus` and `EventSource` to its imports if they are not there — `grep -n '^from\|^import' tests/unit/test_supervisor.py` and add only what is missing.

Calling `_close` directly is deliberate: this test is about the value surviving the write, not about scheduling, and driving it through `tick()` would need a process that exits.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run python -m pytest tests/unit/test_supervisor.py::test_an_idle_records_how_much_of_the_log_the_parent_had_seen -v
```

Expected: FAIL with `TypeError: Idled.__init__() got an unexpected keyword argument` or a Pydantic `ValidationError` naming `seen_through` — the field does not exist anywhere yet.

- [ ] **Step 3: Add the column**

```sql
-- ancalagon/migrations/002_seen_through.up.sql
ALTER TABLE agent_events ADD COLUMN seen_through INTEGER NOT NULL DEFAULT 0;

PRAGMA user_version = 2;
```

```sql
-- ancalagon/migrations/002_seen_through.down.sql
ALTER TABLE agent_events DROP COLUMN seen_through;

PRAGMA user_version = 1;
```

`DROP COLUMN` needs SQLite 3.35+; the interpreter here reports 3.47.1, so it is available. `latest_version` reads the highest `NNN_*.up.sql` in the directory, so adding the pair is all that is needed to make 2 the target.

In `ancalagon/bus/schema.py`, add the column to the table after `summary`:

```python
    sa.Column("summary", sa.Text, nullable=False),
    sa.Column("seen_through", sa.Integer, nullable=False),
```

- [ ] **Step 4: Carry it through the bus**

In `ancalagon/bus/lifecycle_store.py`, `_INSERT_EVENT` gains the bind:

```python
_INSERT_EVENT = sa.insert(agent_events).values(
    agent=sa.bindparam("agent"),
    ts=sa.bindparam("ts"),
    status=sa.bindparam("status"),
    source=sa.bindparam("source"),
    pid=sa.bindparam("pid"),
    summary=sa.bindparam("summary"),
    seen_through=sa.bindparam("seen_through"),
)
```

`record` and `_record` gain the parameter, defaulted the way `pid` and `summary` already are, and `_record` passes it into the insert's parameter dict alongside `"summary"`:

```python
    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
        seen_through: int = 0,
    ) -> None:
```

with the same signature on `_record` and `self._record(agent, status, source, pid, summary, seen_through)` at the call site.

`ancalagon/contracts/agent_event.py` gains `seen_through: int = 0` after `summary`. The default matches the column default, so every event written before this task reads back as zero.

- [ ] **Step 5: Carry it through the outcome**

`ancalagon/contracts/idled.py`:

```python
class Idled(Payload, frozen=True):
    waiting_for: tuple[int, ...]
    seen_through: int

    def text_for_model(self) -> str:
        return f"idling until one of agents {list(self.waiting_for)} finishes"
```

`text_for_model` is unchanged — the watermark is for the scheduler, not for the model.

`ancalagon/contracts/idling.py` gains `seen_through: int`, required. `ancalagon/contracts/outcome_header.py` gains `seen_through: int = 0` — it parses every outcome kind, and only an idling one carries a meaningful value.

Both `Idled` and `Idling` take it as **required**, so every producer states it. That breaks existing construction sites, which is the intent: `grep -rn 'Idling(' ancalagon tests` and `grep -rn 'Idled(' ancalagon tests` and give each one a value. In tests that do not care, `seen_through=0` is the honest value — the producer had seen nothing.

- [ ] **Step 6: Compute it where the decision is made**

In `ancalagon/tools/idle/idle.py`, `run` already takes the snapshot:

```python
    def run(self, args: IdleArgs, ctx: ToolContext) -> ToolResult:
        bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
        snapshot = bus.snapshot()
        live = live_children(snapshot, self.agent)
        if not live:
            return ctx.failure(self.name, "nothing to wait for: no live children")
        seen = max((e.id for events in snapshot.events.values() for e in events), default=0)
        payload = Idled(waiting_for=live, seen_through=seen)
        path = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=path)
```

The watermark is the largest event id **anywhere** in the snapshot, not just among this agent's children — it means "how much of the log I had seen".

In `ancalagon/session.py:228`, stop discarding it:

```python
        if isinstance(summary, Idled):
            return Idling(
                summary=summary.text_for_model()[:SUMMARY_CHARS],
                spent=self._spent(),
                seen_through=summary.seen_through,
            )
```

**There is a second idling path, and it never calls the tool.** `session.py:322` returns
`Idling(summary="turns exhausted while children ran", ...)` when a session runs out of turns with
children still working. It has no `Idled` payload, so it needs its own watermark, and the session
reaches the bus only through `Children`. That protocol gains one method:

```python
# ancalagon/children/children.py
class Children(typing.Protocol):
    def outstanding(self) -> tuple[int, ...]: ...

    def uncollected(self) -> tuple[int, ...]: ...

    def seen_through(self) -> int: ...
```

```python
# ancalagon/children/bus_children.py
    def seen_through(self) -> int:
        snapshot = self.bus.snapshot()
        return max((e.id for events in snapshot.events.values() for e in events), default=0)
```

and `run` reads it **before** it asks what is outstanding:

```python
    def run(self) -> Outcome[pydantic.BaseModel]:
        while True:
            final = self.remaining.turns_exhausted
            seen = self.children.seen_through()
            outstanding = self.children.outstanding()
            if final and outstanding:
                return Idling(
                    summary="turns exhausted while children ran",
                    spent=self._spent(),
                    seen_through=seen,
                )
```

The order matters and is not stylistic. A watermark taken *earlier* than the decision is always
safe: a child settling in between lands above it and wakes the parent, which then finds nothing
new and carries on. A watermark taken *later* can swallow that child, which is the bug this whole
spec is about. Read it first.

Any other `Children` implementation in the test suite needs the method too —
`grep -rn 'Children)' tests` finds them.

In `ancalagon/supervisor/supervisor.py`, `_close` reads it from the header it already parses and `_finish` passes it on:

```python
    def _finish(self, agent: int, status: AgentStatus, summary: str, seen_through: int = 0) -> None:
        self.bus.record(
            agent, status, EventSource.SUPERVISOR, summary=summary, seen_through=seen_through
        )
        self.live = {a: p for a, p in self.live.items() if a != agent}
        self.started = {a: s for a, s in self.started.items() if a != agent}

    def _close(self, agent: int, close: AgentStatus, summary: str) -> None:
        written = pathlib.PurePath(self.bus.dir_of(agent)) / f"outcome-{agent}.json"
        if self.fs.exists(written):
            spoken = OutcomeHeader.model_validate_json(self.fs.read_text(written))
            self._finish(
                agent,
                AgentStatus(spoken.kind.value),
                spoken.summary,
                seen_through=spoken.seen_through,
            )
            return
        self._finish(agent, close, summary)
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
```

Expected: PASS, including every existing supervisor and session test. This task changes no scheduling behaviour, so a test that needed its *assertions* changed — as opposed to a constructor call gaining `seen_through=0` — is evidence something moved. Stop and report it rather than changing it.

- [ ] **Step 8: Mutation-check the round trip**

Break the two hops the new test claims and confirm it fails at each: change `seen_through=seen` in `Idle.run` to `seen_through=0` (the tool's assertion fails), and drop `seen_through=spoken.seen_through` from `_close` (the recorded-event assertion fails). Restore both.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add ancalagon tests
git commit -m "An idle records how much of the log its agent had seen"
```

---

### Task 2: Compare against it

**Files:**
- Modify: `ancalagon/schedule/has_news.py`
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: `AgentEvent.seen_through: int` (Task 1).
- `has_news(snapshot: Snapshot, task: int) -> bool` keeps its signature. Nothing else changes.

- [ ] **Step 1: Write the failing tests**

Three tests, appended to `tests/unit/test_supervisor.py`. The first is the bug; the second and third exist to stop a later reader "simplifying" the fix back into one of the wrong designs.

```python
def _settle(bus: LifecycleStore, agent: int, verdict: AgentStatus) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    bus.record(agent, verdict, EventSource.SUPERVISOR)


def _idled(bus: LifecycleStore, agent: int, seen_through: int) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    bus.record(
        agent, AgentStatus.IDLING, EventSource.SUPERVISOR, seen_through=seen_through
    )


def test_a_parent_wakes_whichever_order_it_and_its_child_are_reaped_in(
    tmp_path: pathlib.Path,
):
    for name, child_first in (("child_first", True), ("parent_first", False)):
        root = tmp_path / name
        root.mkdir()
        migrate_file(root / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
        bus = LifecycleStore.open(root / "bus.db", SystemClock(), RealFileSystem())
        parent = bus.enqueue(root / "tasks" / "parent", parent_agent=0)
        child = bus.enqueue(root / "tasks" / "child", parent_agent=parent)
        watermark = max(e.id for events in bus.snapshot().events.values() for e in events)

        if child_first:
            _settle(bus, child, AgentStatus.COMPLETED)
            _idled(bus, parent, watermark)
        else:
            _idled(bus, parent, watermark)
            _settle(bus, child, AgentStatus.COMPLETED)

        snapshot = bus.snapshot()
        assert has_news(snapshot, task_of(snapshot, parent).id) is True, name


def test_a_child_that_settled_before_the_parent_idled_does_not_wake_it(
    tmp_path: pathlib.Path,
):
    migrate_file(tmp_path / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(tmp_path / "bus.db", SystemClock(), RealFileSystem())
    parent = bus.enqueue(tmp_path / "tasks" / "parent", parent_agent=0)
    stale = bus.enqueue(tmp_path / "tasks" / "stale", parent_agent=parent)
    live = bus.enqueue(tmp_path / "tasks" / "live", parent_agent=parent)

    _settle(bus, stale, AgentStatus.COMPLETED)
    bus.record(live, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(live, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)
    watermark = max(e.id for events in bus.snapshot().events.values() for e in events)
    _idled(bus, parent, watermark)

    snapshot = bus.snapshot()
    task = task_of(snapshot, parent).id
    assert has_news(snapshot, task) is False

    bus.record(live, AgentStatus.COMPLETED, EventSource.SUPERVISOR)
    assert has_news(bus.snapshot(), task) is True


def test_a_child_that_idles_and_is_woken_still_wakes_its_own_parent(
    tmp_path: pathlib.Path,
):
    migrate_file(tmp_path / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(tmp_path / "bus.db", SystemClock(), RealFileSystem())
    top = bus.enqueue(tmp_path / "tasks" / "top", parent_agent=0)
    middle_dir = tmp_path / "tasks" / "middle"
    middle = bus.enqueue(middle_dir, parent_agent=top)
    bottom = bus.enqueue(tmp_path / "tasks" / "bottom", parent_agent=middle)

    bus.record(middle, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(middle, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)
    watermark = max(e.id for events in bus.snapshot().events.values() for e in events)
    _idled(bus, top, watermark)

    _settle(bus, bottom, AgentStatus.COMPLETED)
    bus.record(middle, AgentStatus.IDLING, EventSource.SUPERVISOR, seen_through=watermark)
    resumed = bus.enqueue(middle_dir, parent_agent=top)
    _settle(bus, resumed, AgentStatus.COMPLETED)

    snapshot = bus.snapshot()
    assert has_news(snapshot, task_of(snapshot, top).id) is True
```

Add `has_news` and `task_of` to the file's imports; `task_of` is already imported there, `has_news` is not.

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run python -m pytest tests/unit/test_supervisor.py -k "reaped_in or settled_before or idles_and_is_woken" -v
```

Expected: `test_a_parent_wakes_whichever_order_it_and_its_child_are_reaped_in` FAILS on the `child_first` iteration — that is the bug. The other two PASS already, because today's comparison happens to get them right; they are there to pin that down through the change.

- [ ] **Step 3: Anchor on the watermark**

```python
# ancalagon/schedule/has_news.py
# Whether a task's child has settled with something its parent had not seen when it idled.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.schedule.is_news import is_news
from ancalagon.schedule.newest_agent import newest_agent


def has_news(snapshot: Snapshot, task: int) -> bool:
    parent = newest_agent(snapshot, task)
    match [e for e in snapshot.events[parent] if e.status is AgentStatus.IDLING]:
        case []:
            return False
        case [idled, *_]:
            return any(
                is_news(snapshot, newest_agent(snapshot, child.id))
                and max(e.id for e in snapshot.events[newest_agent(snapshot, child.id)])
                > idled.seen_through
                for child in snapshot.tasks
                if child.parent_agent in snapshot.agents_by_task[task]
            )
```

The module header changes because what the function asks changed. `max(idled)` is gone: an agent produces exactly one outcome, so it has at most one `IDLING` event.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
uv run python -m pytest tests/integration/test_blackboard.py -v
```

Expected: PASS. `test_a_tick_wakes_an_idling_parent_once_a_supervisor_has_reaped_its_child` must still pass unchanged — it drives the whole thing through real `tick()` calls and is the end-to-end proof.

- [ ] **Step 5: Mutation-check**

Break the fix in the two most obvious ways and confirm the right test fails: change `> idled.seen_through` back to comparing against `idled.id` (the reap-order test fails on `child_first`), and drop the `> idled.seen_through` clause entirely (the stale-child test fails on its first assertion). Restore both.

- [ ] **Step 6: Update the living docs**

`docs/architecture.md` describes the wake mechanism around the blackboard and watch sections. Find the sentence that explains when an idling parent is woken and correct it: a parent is woken when a child it had not already seen settles, measured by the event id the parent recorded when it idled, not by when the supervisor noticed the parent stop. Keep it to a sentence or two in the existing voice.

`README.md` does not describe this mechanism; check with `grep -n 'idle\|idling' README.md` and leave it alone if the hits are only the tool table.

- [ ] **Step 7: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
uv run python -m pytest tests/integration/test_blackboard.py
git add ancalagon tests docs/architecture.md
git commit -m "An idling parent wakes on what it had not yet seen"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: the column, the plumbing and `Idle` reading the watermark to Task 1; the comparison, `max(idled)`'s removal and the three tests to Task 2. The spec's four enumerated cases are covered by the three tests plus the existing `test_a_tick_wakes_an_idling_parent_once_a_supervisor_has_reaped_its_child` — reap-order both ways, stale child, nested parent woken, and the ordinary case that already worked.

The spec's "Deterministic agents" section deliberately has no task: it names the `live_children` guard a run function will need and says it has no caller yet.

**One decision the spec left open and this plan settles.** `Idled.seen_through` and `Idling.seen_through` are **required**, while `AgentEvent.seen_through` and `OutcomeHeader.seen_through` default to zero. A producer of an idle must state what it had seen; a reader of arbitrary events must tolerate the ones written before the column existed and the four outcome kinds that never carry one.

**One thing the plan adds that the spec does not name.** `Supervisor._finish` gains a `seen_through` parameter, because `_close` is not the only caller — `_spawn` and `_reap_timeout` call it too, and they legitimately have no watermark.

**Types.** `seen_through` is `int` at every hop — `Idled`, `Idling`, `OutcomeHeader`, `AgentEvent`, `record`/`_record`, `_finish`, and the SQLite column. `has_news` keeps `(snapshot: Snapshot, task: int) -> bool`. The test helpers `_settle` and `_idled` are defined once in Task 2 and used by all three of its tests.
