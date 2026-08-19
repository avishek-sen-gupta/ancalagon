# Agent Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the supervisor guessing about attempts it does not own, then state the agent lifecycle once and enforce it where events are written.

**Architecture:** Part one replaces two never-justified supervisor rules — `shutdown` marking live workers `abandoned`, and a new supervisor marking a previous one's rows `abandoned` and aborting the run — with a single startup resolution that checks the recorded pid instead of assuming. Part two folds an agent's event history into one state (`Queued`, `Claimed`, `Running`, `Reported`, `Closed`, `Lost`, `Collected`), reimplements every "is this done" predicate over that fold, and rejects illegal transitions inside `Bus.record`.

**Tech Stack:** Python 3.13, Pydantic v2, SQLite (stdlib), pytest, Pyright strict.

**Spec:** `docs/superpowers/specs/2026-08-19-agent-lifecycle-design.md`

## Global Constraints

- Pyright strict, **zero errors**. `Any` banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and hand-rolled recursive JSON types banned for the same reason.
- Every generic parameterised: `list[AgentEvent]`, never bare `list`.
- **No comments** except a one-line header on a class or module. No docstrings, no inline explanations, no section dividers, no TODOs.
- All Pydantic models `frozen=True`. **One class per file.** Fully qualified imports, no relative imports.
- A class implementing a `Protocol` **inherits** it.
- `Sequence`/`Mapping`/`Collection` from `collections.abc` for parameters that are not mutated.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance`, no bare `except`, no workaround guards. Use a null object or a distinct type instead.
- **Never ask an agent's *latest* status what happened to it.** A worker records its own account and the supervisor appends `exited` over it, so an idled agent and a completed one are the same row by latest status. This defect has shipped four times in this area.
- **Never ask an *agent* a question about a *task*.** `tasks.parent_agent` is written only when the task row is new.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file. Concrete assertions, never `assert x is not None`.
- **No mocking.** `unittest.mock.patch` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, `FakeProcess`, `FakeSpawner`.
- A shipped migration is never edited **except** `001_init`, which is the only migration and is edited in place; run directories are disposable and no backward compatibility is promised.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`.
- The `python-fp-lint` pre-commit hook lints **staged content of staged files**, so it reports pre-existing debt in any older file a change touches. Run `pre-commit run --all-files` with work **staged** — unstaged changes are stashed and give a false pass. `--no-verify` only for violations on lines your diff does not modify, stated in the commit message. **Never `git stash`** — use `git worktree add` or `git show HEAD:<path>`.
- Never reference an external codebase in a tracked artifact.

---

## File Structure

**Created**
- `ancalagon/supervisor/liveness.py` — `Liveness` protocol, one method: `is_running(pid: int) -> bool`.
- `ancalagon/supervisor/os_liveness.py` — `OsLiveness`, using `os.kill(pid, 0)`.
- `ancalagon/supervisor/fake_liveness.py` — `FakeLiveness(alive: frozenset[int])` for tests, since `no mocking` forbids patching `os.kill`.
- `ancalagon/bus/attempt.py` — the seven lifecycle states as one union.
- `ancalagon/bus/attempt_of.py` — `attempt_of(events) -> Attempt`, the pure fold.
- `ancalagon/bus/illegal_transition.py` — the error `Bus.record` raises.

**Modified**
- `ancalagon/supervisor/supervisor.py` — `shutdown` stops recording; startup resolution replaces the orphan branch.
- `ancalagon/bus/bus.py` — `resolve_stale`, then every predicate reimplemented over `attempt_of`; `record` enforces.
- `ancalagon/bus/agent_status.py` — `ABANDONED` deleted.
- `ancalagon/migrations/001_init.up.sql` / `.down.sql` — `'abandoned'` removed from the status `CHECK`.
- `tests/unit/conftest.py` — the `settle` helper.

---

### Task 1: The supervisor checks instead of assuming

**Files:**
- Create: `ancalagon/supervisor/liveness.py`, `ancalagon/supervisor/os_liveness.py`, `ancalagon/supervisor/fake_liveness.py`
- Modify: `ancalagon/bus/bus.py`, `ancalagon/supervisor/supervisor.py`
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Produces: `Liveness` protocol with `is_running(pid: int) -> bool`; `OsLiveness`; `FakeLiveness(alive: frozenset[int])`; `Bus.resolve_stale(liveness: Liveness) -> None`; `Supervisor(..., liveness: Liveness = OS_LIVENESS)`.

`Liveness` is a port for the same reason `Clock` and `Meter` are: the project bans mocking, so `os.kill` has to be injectable to be testable. `OS_LIVENESS` is a module-level singleton because Ruff's B008 forbids a call in a default argument — `UNMETERED` and `NO_CHILDREN` are the precedents.

`resolve_stale` is on `Bus` rather than `Supervisor` because it is a database repair, and it takes the port rather than importing it.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_supervisor.py`, following the fixture style already there:

```python
def test_startup_resolves_stale_rows_by_checking_the_pid(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    spoke = bus.enqueue(tmp_path / "spoke", parent_agent=HUMAN)
    alive = bus.enqueue(tmp_path / "alive", parent_agent=HUMAN)
    dead = bus.enqueue(tmp_path / "dead", parent_agent=HUMAN)
    never = bus.enqueue(tmp_path / "never", parent_agent=HUMAN)

    for agent, pid in ((spoke, 101), (alive, 102), (dead, 103)):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(spoke, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(never, AgentStatus.CLAIMED, EventSource.SUPERVISOR)

    bus.resolve_stale(FakeLiveness(frozenset({102})))

    assert bus.state(spoke).status is AgentStatus.EXITED
    assert bus.state(alive).status is AgentStatus.RUNNING
    assert bus.state(dead).status is AgentStatus.CRASHED
    assert bus.state(never).status is AgentStatus.CRASHED
```

Four rows, four outcomes. `spoke` is the one the old code got worst: it finished its work and the old sweep marked it dead.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_supervisor.py -k resolves_stale -v`
Expected: FAIL with `ImportError: cannot import name 'FakeLiveness'`.

- [ ] **Step 3: Write the port and its two implementations**

`ancalagon/supervisor/liveness.py`:

```python
# Whether a process this supervisor does not own is still running.
import typing


class Liveness(typing.Protocol):
    def is_running(self, pid: int) -> bool: ...
```

`ancalagon/supervisor/os_liveness.py`:

```python
# Asks the operating system whether a pid exists, which is all it can tell us.
import os

from ancalagon.supervisor.liveness import Liveness


class OsLiveness(Liveness):
    def is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


OS_LIVENESS = OsLiveness()
```

`PermissionError` means the process exists and belongs to another user, so it is alive. These are the two specific exceptions `os.kill(pid, 0)` raises; catching them by name rather than a bare `except` is what the guardrails require.

`ancalagon/supervisor/fake_liveness.py`:

```python
# A Liveness that answers from a fixed set, so a test can decide who is running.
from ancalagon.supervisor.liveness import Liveness


class FakeLiveness(Liveness):
    def __init__(self, alive: frozenset[int]):
        self.alive = alive

    def is_running(self, pid: int) -> bool:
        return pid in self.alive
```

- [ ] **Step 4: Implement `Bus.resolve_stale`**

For each agent from `self.unreaped()`, read `self.history(agent)` and decide:

- any worker-sourced status in `{COMPLETED, EXHAUSTED, FAILED, NEEDS_INPUT, IDLING}` present → `record(agent, AgentStatus.EXITED, EventSource.SUPERVISOR, summary="closed at startup; worker had reported")`
- else a `RUNNING` event whose `pid` `liveness.is_running(...)` → leave it untouched
- else → `record(agent, AgentStatus.CRASHED, EventSource.SUPERVISOR, exit_code=-1, summary="no live process at startup")`

The `RUNNING` event's `pid` comes from history, not from `state(agent).pid` — the latest row is not the `running` row once a worker has spoken.

- [ ] **Step 5: Rewire the supervisor**

`Supervisor.__init__` takes `liveness: Liveness = OS_LIVENESS` and stores it. `run_until_idle` calls `self.bus.resolve_stale(self.liveness)` **once before the loop**, and its orphan branch is deleted entirely — no `unreaped()` check, no `return`. `shutdown` becomes:

```python
    def shutdown(self) -> None:
        self.live.clear()
        self.started.clear()
```

It no longer kills and no longer records. A worker that outlives the supervisor finishes and writes its verdict; the next startup adopts it.

- [ ] **Step 6: Verify**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`

Existing tests asserting `ABANDONED` after shutdown will fail. That is the behaviour change; rewrite them to assert what now happens — the process is left alone and the row is resolved on the next startup — rather than deleting them.

- [ ] **Step 7: Mutation-check**

Three, all must fail. Make `resolve_stale` record `CRASHED` for the `spoke` case and confirm the `EXITED` assertion fails. Make it ignore `liveness` and always record `CRASHED`, and confirm the `alive` assertion fails. Make `shutdown` record `ABANDONED` again and confirm the rewritten shutdown test fails.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "The supervisor checks a pid instead of assuming a corpse"
```

---

### Task 2: `ABANDONED` loses its producers and goes

**Files:**
- Modify: `ancalagon/bus/agent_status.py`, `ancalagon/migrations/001_init.up.sql`, `ancalagon/migrations/001_init.down.sql`
- Test: `tests/unit/test_migrations.py`

**Interfaces:**
- Consumes: Task 1, which removed both writers.

Task 1 deleted the only two places that wrote `abandoned`. A status with no producer is dead code in the schema.

- [ ] **Step 1: Write the failing test**

Extend `test_migrations_round_trip_and_checks_reject_bad_rows`, which already asserts the `CHECK` rejects an unknown status:

```python
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) "
            "VALUES (1, 't', 'abandoned', 'supervisor')"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_migrations.py -v`
Expected: FAIL — the insert succeeds, because `'abandoned'` is still in the `CHECK` list.

- [ ] **Step 3: Remove it**

Delete `ABANDONED` from `AgentStatus` and from `TERMINAL`, and remove `'abandoned'` from the status `CHECK` in both `001_init.up.sql` and `001_init.down.sql`. Then `grep -rn "abandoned\|ABANDONED" ancalagon tests docs/architecture.md README.md` and remove every remaining reference, including prose.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration
git add -A
git commit -m "A status nothing writes is not a status"
```

---

### Task 3: The lifecycle as one fold

**Files:**
- Create: `ancalagon/bus/attempt.py`, `ancalagon/bus/attempt_of.py`
- Test: `tests/unit/test_attempt.py`

**Interfaces:**
- Produces: `Attempt = Queued | Claimed | Running | Reported | Closed | Lost | Collected` and `attempt_of(events: Sequence[AgentEvent]) -> Attempt`.

This task adds no behaviour and changes no caller. It is the derivation everything else is rebuilt on, tested alone.

**One class per file is a guardrail**, but seven single-field models in seven files for one closed union is the letter against the spirit. Put the union's members in `attempt.py` together, with the module header naming it as one type — the codebase already does this for `ContractPair`-style groupings. If the reviewer disagrees, splitting later is mechanical.

```python
# The seven states an attempt can be in, folded from its events.
import typing

import pydantic

from ancalagon.bus.agent_status import AgentStatus


class Queued(pydantic.BaseModel, frozen=True): ...
class Claimed(pydantic.BaseModel, frozen=True): ...
class Running(pydantic.BaseModel, frozen=True):
    pid: int
class Reported(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
class Closed(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
class Lost(pydantic.BaseModel, frozen=True):
    close: AgentStatus
class Collected(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
    spoke: bool

Attempt = Queued | Claimed | Running | Reported | Closed | Lost | Collected
```

`Collected` carries `spoke` because a parent may collect either a `Closed` or a `Lost` attempt, and the two differ in whether the outcome file is the worker's own or one the supervisor synthesised.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_attempt.py`. Build event lists directly — this is a pure function and needs no bus:

```python
def _events(*pairs: tuple[AgentStatus, EventSource]) -> list[AgentEvent]:
    return [
        AgentEvent(id=i, agent=1, ts="t", status=s, source=src, pid=0, exit_code=0, summary="")
        for i, (s, src) in enumerate(pairs, start=1)
    ]


def test_every_lifecycle_path_folds_to_the_state_it_describes():
    W, S = EventSource.WORKER, EventSource.SUPERVISOR

    assert attempt_of(_events((AgentStatus.QUEUED, S))) == Queued()
    assert attempt_of(_events((AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S))) == Claimed()
    assert attempt_of(
        _events((AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.CRASHED, S))
    ) == Lost(close=AgentStatus.CRASHED)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.RUNNING, S),
            (AgentStatus.IDLING, W),
        )
    ) == Reported(verdict=AgentStatus.IDLING)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.RUNNING, S),
            (AgentStatus.FAILED, W), (AgentStatus.EXITED, S),
        )
    ) == Closed(verdict=AgentStatus.FAILED)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.RUNNING, S),
            (AgentStatus.TIMED_OUT, S),
        )
    ) == Lost(close=AgentStatus.TIMED_OUT)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.RUNNING, S),
            (AgentStatus.COMPLETED, W), (AgentStatus.EXITED, S), (AgentStatus.COLLECTED, W),
        )
    ) == Collected(verdict=AgentStatus.COMPLETED, spoke=True)
```

The `FAILED` case is the axis stated as a test: a worker that caught an exception, wrote its outcome and reported it **spoke**, so it is `Closed(FAILED)` and never `Lost`.

`Running`'s `pid` is asserted separately, from an event list whose `running` row carries a real pid.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_attempt.py -v`
Expected: FAIL with `ImportError: cannot import name 'attempt_of'`.

- [ ] **Step 3: Write the fold**

`attempt_of` walks the events in order, carrying the state forward. Use `match` on `(state, event.status, event.source)`. Verdicts are `{COMPLETED, EXHAUSTED, FAILED, NEEDS_INPUT, IDLING}` from a worker; closes are `{EXITED, CRASHED, TIMED_OUT}` from the supervisor.

- [ ] **Step 4: Verify, mutation-check, commit**

Run the unit suite. Then make the fold treat a worker's `FAILED` as a close rather than a verdict, and confirm the `Closed(verdict=FAILED)` assertion fails. Then drop `spoke` from `Collected` and confirm the last assertion fails.

```bash
git add -A
git commit -m "An attempt's events fold to one state"
```

---

### Task 4: Every predicate reimplemented over the fold

**Files:**
- Modify: `ancalagon/bus/bus.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `attempt_of`, `Attempt` (Task 3).
- Produces: `Bus.attempt(agent: int) -> Attempt`. `live()`, `unreaped()`, `_reaped()`, `outstanding()`, `live_children()`, `uncollected()`, `_has_news()` keep their signatures and are reimplemented.

`live()` has **zero production callers** — verified. Delete it rather than reimplementing it; one of the four spellings costs nothing to remove.

The others become state questions:

| predicate | becomes |
|---|---|
| `unreaped()` | attempt is `Claimed`, `Running`, or `Reported` |
| `_reaped(agent)` | attempt is `Closed`, `Lost`, or `Collected` |
| `outstanding(task)` | newest attempt is `Queued`/`Claimed`/`Running`/`Reported`, **or** `Closed(IDLING)`/`Collected(IDLING, …)` |
| `uncollected(task)` | child's newest attempt is settled and not `Collected` |

`_has_news`'s conjunction `_reaped(newest) and not outstanding(child)` collapses. Once the attempt is `Closed` or `Lost`, `outstanding` can only be true via `idling` — so the clause silently meant *"the child did not itself idle"*. Say that instead: the child's newest attempt is `Closed(verdict)` with `verdict is not IDLING`, or `Lost`.

- [ ] **Step 1: Write the failing test**

Extend the existing bus behaviour test with the case the old conjunction hid:

```python
    assert bus.wakeable() == []
    bus.record(child, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(child, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.wakeable() == []

    bus.record(other, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(other, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]
```

A child that idled and was closed is **not** news for its parent — it has not answered, and it will itself be woken.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k wakeable -v`
Expected: PASS before the rewrite and PASS after — this assertion pins behaviour the conjunction already had, so that the rewrite cannot lose it. Confirm it passes now, then keep it green through Step 3. If it fails now, the conjunction was already wrong and that is a finding to report.

- [ ] **Step 3: Reimplement**

Add `Bus.attempt(agent)` returning `attempt_of(self.history(agent))`, then rewrite each predicate above it. Delete `live()`. `unreaped()` was raw SQL with two `EXISTS` clauses; it becomes a filter over attempts, which is slower and vastly clearer — it runs once per startup.

- [ ] **Step 4: Verify, mutation-check, commit**

Run both suites. Then make `outstanding` treat `Closed(IDLING)` as settled and confirm an idling parent stops being wakeable at all. Then make `_has_news` accept `Closed(IDLING)` as news and confirm the Step 1 assertion fails.

```bash
git add -A
git commit -m "One derivation, and the predicates read from it"
```

---

### Task 5: Illegal transitions are rejected at the write

**Files:**
- Create: `ancalagon/bus/illegal_transition.py`
- Modify: `ancalagon/bus/bus.py`, `ancalagon/tools/delegate/collect_task.py`
- Test: `tests/unit/conftest.py`, `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `Bus.attempt` (Task 4).
- Produces: `IllegalTransition(Exception)`; `Bus.record` raising it; `settle(bus, agent, verdict)` in `conftest.py`.

`Bus.record` is the single choke point — `enqueue`, `claim`, the supervisor and the tools all go through it. It derives the current attempt, rejects an illegal transition, and writes, in one transaction.

**`Reported → Collected` becomes illegal**, which is a behaviour change: today `collect_task` may read a child whose process is still exiting, because a worker verdict alone makes the task not-outstanding. `CollectTask.run` must now require the child's newest attempt to be `Closed` or `Lost`, and fail with a message saying the child has not been closed yet.

- [ ] **Step 1: Write the `settle` helper**

In `tests/unit/conftest.py`:

```python
def settle(bus: Bus, agent: int, verdict: AgentStatus, pid: int = 1) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(agent, verdict, EventSource.WORKER)
    bus.record(agent, AgentStatus.EXITED, EventSource.SUPERVISOR)
```

Sixty-two `record` calls exist across the suite, most jumping from `enqueue` straight to a verdict. Each such site becomes one `settle` call.

- [ ] **Step 2: Write the failing test**

```python
def test_record_refuses_a_transition_the_lifecycle_does_not_allow(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    agent = bus.enqueue(tmp_path / "a", parent_agent=HUMAN)

    with pytest.raises(IllegalTransition, match="collected"):
        bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)
    with pytest.raises(IllegalTransition, match="running"):
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)

    settle(bus, agent, AgentStatus.COMPLETED)
    bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)

    with pytest.raises(IllegalTransition, match="collected"):
        bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)
```

Four assertions: cannot collect what has not run, cannot run what was not claimed, can collect once closed, cannot collect twice.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k refuses_a_transition -v`
Expected: FAIL with `ImportError: cannot import name 'IllegalTransition'`.

- [ ] **Step 4: Implement**

Add a pure `next_state(current: Attempt, status: AgentStatus, source: EventSource) -> Attempt` beside the fold, raising `IllegalTransition` naming the current state, the rejected status and the source. `Bus.record` calls it inside its transaction before the `INSERT`.

- [ ] **Step 5: Convert the suite**

Run the unit suite and convert every failing fixture to `settle`. Do not exempt tests from enforcement and do not weaken an assertion to accommodate a fixture: a fixture that cannot write a legal sequence is describing a run that cannot happen.

- [ ] **Step 6: Gate `collect_task`**

`CollectTask.run` requires `bus.attempt(bus.newest_agent(state.task))` to be `Closed` or `Lost` before reading. Otherwise `ctx.failure(self.name, f"agent {state.agent} has not been closed yet")`.

- [ ] **Step 7: Verify, mutation-check, commit**

Run both suites. Then allow `Reported → Collected` again and confirm the `collect_task` test fails. Then make `next_state` return the current state instead of raising, and confirm all four assertions in Step 2 fail.

```bash
git add -A
git commit -m "The bus refuses to record a transition that cannot happen"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Read both documents end to end before editing**

A grep finds a dead identifier; it cannot find a true-sounding sentence describing behaviour that no longer exists. Both documents describe the supervisor's orphan and shutdown behaviour, which this plan replaces.

- [ ] **Step 2: Write what changed**

Cover: the seven states and that the axis is whether an attempt *spoke*, not whether it succeeded; that `Bus.record` rejects an illegal transition; that a parent must wait for the supervisor's close before collecting; that `shutdown` no longer kills or records, and a worker outliving the supervisor is adopted at the next startup; that startup resolves stale rows by checking the recorded pid, and that pid reuse is a known hole; that `abandoned` no longer exists.

`docs/architecture.md` currently says *"It never retries. A crash is reported; the parent decides."* — that is still true and should stay. Check it rather than rewriting it.

- [ ] **Step 3: Grep for what you missed**

```bash
grep -rn "abandoned\|orphan\|in_flight\|unreaped" README.md docs/architecture.md
```

Expected: no match describes behaviour that no longer exists.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Document the lifecycle, and what the supervisor no longer assumes"
```

---

## Self-Review

**Spec coverage.** Shutdown records nothing → Task 1. Startup resolves by pid → Task 1. The loop no longer returns → Task 1. No automatic retry → Task 1, by omission, asserted by the unchanged architecture.md line in Task 6. `ABANDONED` deleted → Task 2. The seven states and the spoke/silent axis → Task 3. Predicates over one derivation, and the `_has_news` conjunction named → Task 4. Enforcement at `record`, `Reported → Collected` illegal, the `settle` helper → Task 5. Docs → Task 6.

**Three things left for the implementer to settle, flagged rather than guessed:**

1. Whether the seven state classes live in one file or seven (Task 3). One closed union in one file is the spirit of the guardrail; a reviewer may disagree, and splitting is mechanical.
2. What `resolve_stale` does with an attempt that is `Running` with a *live* pid but whose task the supervisor does not intend to adopt (Task 1). Leaving it untouched is specified; whether the supervisor should also start watching it is out of scope and would need a design.
3. Whether `unreaped()` survives Task 4 with a caller (Task 4). After Task 1 its only production caller is `resolve_stale`; if that inlines the filter, `unreaped` is dead and should go.

**Known and accepted, from the spec:** the pid check cannot distinguish a reused pid from the original process; two supervisors sharing one `bus.db` each see only their own; the N+1 reads in `_has_news` and `uncollected` are unchanged; states are not moved out to call sites.

**Type consistency.** `Liveness.is_running(pid: int) -> bool`, `OS_LIVENESS`, `FakeLiveness(alive: frozenset[int])`, `Bus.resolve_stale(liveness: Liveness) -> None`, `Bus.attempt(agent: int) -> Attempt`, `attempt_of(events: Sequence[AgentEvent]) -> Attempt`, `next_state(current, status, source) -> Attempt`, `IllegalTransition`, `settle(bus, agent, verdict, pid=1)` are used identically in every task that mentions them.
