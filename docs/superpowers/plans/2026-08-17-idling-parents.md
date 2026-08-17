# Idling Parents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a parent stop and be woken when a child finishes, instead of spending turns asking whether one has.

**Architecture:** A parent with live children is offered `idle` and not offered `submit_answer`, so it cannot finish without accounting for them and cannot poll to find out. Calling `idle` ends the attempt with an `Idling` outcome; the process exits and its state stays on disk. When any child reaches a terminal status the supervisor re-enqueues the parent's task, which reuses the task row and adds a new agent, and the new worker rebuilds the session from the transcript — the same path `answer_task` already uses.

**Tech Stack:** Python 3.13, Pydantic v2, SQLite (stdlib), pytest, Pyright strict.

**Spec:** `docs/superpowers/specs/2026-08-17-idling-parents-design.md`

## Global Constraints

- Pyright strict, **zero errors**. `Any` banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and hand-rolled recursive JSON types banned for the same reason.
- Every generic parameterised: `list[AgentState]`, never bare `list`.
- **No comments** except a one-line header on a class or module. No docstrings, no inline explanations, no section dividers, no TODOs.
- All Pydantic models `frozen=True`. One class per file. Fully qualified imports, no relative imports.
- `Sequence`/`Mapping` from `collections.abc` for parameters that are not mutated.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance`, no bare `except`, no workaround guards.
- Text is a boundary, never a carrier: JSON becomes a model via `model_validate_json` at the boundary and is serialised only at a file write or the wire.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file. Concrete assertions (`assert result == 30`), never `assert x is not None`.
- **No mocking.** `unittest.mock.patch` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, fake spawners.
- **A guard that reads an agent's *latest* status is almost always wrong.** Statuses are appended, not replaced, and a worker records its terminal status before the supervisor records `exited` — so the last event says `exited` and the interesting one is further back. Ask whether the history *contains* what you care about, inside the transaction that acts on the answer. This defect has already shipped once in this codebase, in `answer_task`.
- A shipped migration is never edited. Add a numbered one.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`.
- The `python-fp-lint` pre-commit hook lints **staged content of staged files**, so it reports pre-existing debt in any older file a change touches. Run `pre-commit run --all-files` with work **staged** — unstaged changes are stashed and give a false pass. `--no-verify` only for violations on lines your diff does not modify, stated in the commit message.
- Never reference an external codebase in a tracked artifact.

---

## File Structure

**Created**
- `ancalagon/contracts/idling.py` — the `Idling` outcome.
- `ancalagon/contracts/idled.py` — the payload `idle` returns, marking the attempt as idling.
- `ancalagon/tools/idle/idle.py`, `idle_args.py` — the tool.
- `ancalagon/migrations/004_idling_status.up.sql` / `.down.sql` — the `status` CHECK constraint.

**Modified**
- `ancalagon/contracts/outcome_kind.py`, `outcome.py` — the new kind and the union.
- `ancalagon/bus/agent_status.py` — `IDLING`, and its place in `TERMINAL`.
- `ancalagon/bus/bus.py` — `live_children`, and `resumable_idle`.
- `ancalagon/worker.py` — `build_registry` chooses between `submit_answer` and `idle`.
- `ancalagon/session.py` — `idle` ends the attempt; exhaustion with live children idles.
- `ancalagon/supervisor/supervisor.py` — re-enqueue an idling parent when a child finishes.
- `README.md`, `docs/architecture.md`, `ancalagon.example.toml`.

---

### Task 1: The `Idling` outcome, status, and migration

**Files:**
- Create: `ancalagon/contracts/idling.py`, `ancalagon/migrations/004_idling_status.up.sql`, `ancalagon/migrations/004_idling_status.down.sql`
- Modify: `ancalagon/contracts/outcome_kind.py`, `ancalagon/contracts/outcome.py`, `ancalagon/bus/agent_status.py`
- Test: `tests/unit/test_migrations.py`

**Interfaces:**
- Produces: `OutcomeKind.IDLING`, `AgentStatus.IDLING` (in `TERMINAL`), `Idling(kind, summary, spent)`, schema version 4.

`Idling` carries no value: the parent has not answered. It carries `spent` like every other outcome, so a run's accounting still adds up.

SQLite cannot alter a `CHECK` constraint, so the migration recreates `agent_events`: create the new table, copy every row, drop the old, rename. The `.down.sql` does the same in reverse and must **delete rows whose status is `idling`** before restoring the old constraint, or the copy fails.

- [ ] **Step 1: Write the failing test**

Extend `test_migrations_round_trip_and_checks_reject_bad_rows` in `tests/unit/test_migrations.py`. It already asserts `latest_version() == 3` and that a bogus status is rejected — change the version and add the new status:

```python
    assert latest_version() == 4
    ...
    conn.execute(
        "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'idling', 'worker')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'bogus', 'worker')"
        )

    migrate(conn, 3)
    assert user_version(conn) == 3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) VALUES (1, 't', 'idling', 'worker')"
        )
```

The last three lines are the point: going *down* must restore the old constraint, not merely renumber the version.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_migrations.py -v`
Expected: FAIL on `assert latest_version() == 4`.

- [ ] **Step 3: Write the migration**

`004_idling_status.up.sql` — copy the `agent_events` definition from `001_init.up.sql:18-29` verbatim, add `'idling'` to the status list, and:

```sql
ALTER TABLE agent_events RENAME TO agent_events_old;

CREATE TABLE agent_events ( ... 'abandoned', 'exited', 'idling')), ... );

INSERT INTO agent_events SELECT * FROM agent_events_old;
DROP TABLE agent_events_old;

PRAGMA user_version = 4;
```

`004_idling_status.down.sql` does the reverse, deleting idling rows first:

```sql
DELETE FROM agent_events WHERE status = 'idling';
ALTER TABLE agent_events RENAME TO agent_events_old;
CREATE TABLE agent_events ( ... without 'idling' ... );
INSERT INTO agent_events SELECT * FROM agent_events_old;
DROP TABLE agent_events_old;

PRAGMA user_version = 3;
```

- [ ] **Step 4: Add the kind, the status and the outcome**

`ancalagon/contracts/idling.py`:

```python
# What an attempt returns when it stops to wait for its children.
import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class Idling(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.IDLING] = OutcomeKind.IDLING
    summary: str
    spent: Budget
```

Add `IDLING = "idling"` to `OutcomeKind`; add `IDLING = "idling"` to `AgentStatus` **and to `TERMINAL`** — an idling attempt has ended, and the supervisor must not treat the process as live. Add `Idling` to the `Outcome` union and to `outcome_adapter`'s adapter, both in `outcome.py`.

- [ ] **Step 5: Run tests, verify, commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
git add -A && git commit -m "An attempt can end by idling"
```

- [ ] **Step 6: Mutation-check**

Remove `'idling'` from the up-migration's CHECK list and confirm the insert assertion fails. Then remove the `DELETE` from the down-migration and confirm the downgrade assertion fails. Restore both.

---

### Task 2: The bus knows a parent's children

**Files:**
- Modify: `ancalagon/bus/bus.py`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `AgentStatus.IDLING`, `TERMINAL` from Task 1.
- Produces: `Bus.live_children(agent: int) -> list[AgentState]`, `Bus.resumable_idle(agent: int) -> bool`.

`tasks.parent_agent` already records which agent spawned each task, written by `enqueue` and used by `depth_of`. Both queries read it; neither adds state.

`resumable_idle` is where the appended-status trap lives. A worker records `idling` and the supervisor then records `exited`, so the parent's **latest** status is `exited` and a latest-status check would never fire. Ask whether the history since the parent's most recent `queued` event *contains* `idling`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_bus.py`, following the fixture style already there:

```python
def test_the_bus_knows_which_children_are_live_and_which_parents_may_resume(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    first = bus.enqueue(tmp_path / "a", parent_agent=parent)
    second = bus.enqueue(tmp_path / "b", parent_agent=parent)

    assert [s.agent for s in bus.live_children(parent)] == [first, second]
    assert bus.resumable_idle(parent) is False

    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(parent, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.resumable_idle(parent) is True

    bus.record(first, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(first, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [s.agent for s in bus.live_children(parent)] == [second]

    resumed = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    assert resumed != parent
    assert bus.resumable_idle(resumed) is False
```

The `EXITED` records after each terminal status are the point — that is what production writes, and a latest-status implementation passes every line except `resumable_idle(parent) is True`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -k live_children -v`
Expected: FAIL with `AttributeError: 'Bus' object has no attribute 'live_children'`.

- [ ] **Step 3: Implement both queries**

```python
    def live_children(self, agent: int) -> list[AgentState]:
        return self._states(
            f"WHERE t.parent_agent = ? AND e.status NOT IN ({TERMINAL_MARKS}) ORDER BY a.id",
            (agent, *TERMINAL_VALUES),
        )

    def resumable_idle(self, agent: int) -> bool:
        events = self.history(agent)
        since = [e.status for e in events]
        return AgentStatus.IDLING in since
```

`history` returns this agent's events only, and an agent id is never reused — `enqueue` inserts a new agent row per attempt — so "contains `idling`" is already scoped to one attempt and needs no `queued` boundary. Confirm that by reading `enqueue` before relying on it; if an agent id *can* be reused, scope to the events after the last `queued` instead.

- [ ] **Step 4: Run, verify, commit**

```bash
uv run python -m pytest tests/unit/test_bus.py -v
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
git add -A && git commit -m "The bus can say which children are live, and which parent may resume"
```

- [ ] **Step 5: Mutation-check**

Reimplement `resumable_idle` as `self.state(agent).status is AgentStatus.IDLING` and confirm the test fails on the `is True` assertion — that is the defect this test exists to catch.

---

### Task 3: `idle`, and the tool surface that depends on children

**Files:**
- Create: `ancalagon/contracts/idled.py`, `ancalagon/tools/idle/idle.py`, `ancalagon/tools/idle/idle_args.py`, `ancalagon/tools/idle/__init__.py`
- Modify: `ancalagon/worker.py`, `ancalagon/session.py`
- Test: `tests/unit/test_tools.py`, `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: `Bus.live_children` (Task 2), `Idling` (Task 1).
- Produces: the `idle` tool; `build_registry` offering `idle` xor `submit_answer`.

`Idled` follows `Asked` — a `Payload` the session recognises to end the attempt:

```python
# What idle returns: the attempt stops here and resumes when a child finishes.
from ancalagon.contracts.payload import Payload


class Idled(Payload, frozen=True):
    waiting_for: tuple[int, ...]

    def text_for_model(self) -> str:
        return f"idling until one of agents {list(self.waiting_for)} finishes"
```

`IdleArgs` has no fields. `Idle` takes `run_dir`, `agent` and `clock`, opens the bus like `CheckTask` does, and **fails when there are no live children** rather than stopping — a run must not be able to sleep with everything idle.

**The registry rule, and the wrinkle you must document rather than fix.** `build_registry` runs once per attempt. If the agent has live children it offers `idle` and withholds `submit_answer`; otherwise the reverse. Children that finish *during* an attempt do not bring `submit_answer` back — the parent idles once more and gets it on the next attempt, costing one extra wake. That is the intended trade: a registry rebuilt per turn is a larger change than this plan carries. Say so in the report.

- [ ] **Step 1: Write the failing test**

```python
def test_a_parent_with_live_children_is_offered_idle_instead_of_submit_answer(
    tmp_path: pathlib.Path,
):
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version())
    bus = Bus.open(run_dir / "bus.db", FakeClock())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN)
    child = bus.enqueue(run_dir / "tasks" / "c", parent_agent=parent)

    waiting = build_registry(..., parent=parent, ...)
    assert "idle" in waiting.names()
    assert "submit_answer" not in waiting.names()

    result = waiting.get("idle").invoke("{}", _ctx(tmp_path))
    assert result.ok is True
    assert result.summary == Idled(waiting_for=(child,))

    bus.record(child, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(child, AgentStatus.EXITED, EventSource.SUPERVISOR)
    settled = build_registry(..., parent=parent, ...)
    assert "submit_answer" in settled.names()
    assert "idle" not in settled.names()

    refused = waiting.get("idle").invoke("{}", _ctx(tmp_path))
    assert refused.ok is False
    assert "nothing to wait for" in refused.error
```

Fill the `build_registry` arguments from the existing registry test in that file rather than inventing them.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_tools.py -k offered_idle -v`
Expected: FAIL with `ImportError` on `Idled`.

- [ ] **Step 3: Write the tool and wire the registry**

`Idle.run` reads `bus.live_children(self.agent)`; empty means `ctx.failure(self.name, "nothing to wait for: no live children")`, otherwise `ToolResult(ok=True, summary=Idled(waiting_for=tuple(s.agent for s in live)), path=ctx.write_output(...))`. `cost = 0` — idling is not work, and charging for it would recreate the incentive to poll.

In `build_registry`, compute `live = bus.live_children(parent)` once and choose between the two tools. `build_registry` does not take a bus today; pass one rather than opening a second connection.

- [ ] **Step 4: Make the session end on `Idled`**

In `Session._run_tools`'s result loop, beside the `Asked` and `Submitted` branches:

```python
                    if isinstance(result.summary, Idled):
                        return Idling(
                            summary=result.summary.text_for_model()[:SUMMARY_CHARS],
                            spent=self._spent(),
                        )
```

- [ ] **Step 5: Run, verify, commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
git add -A && git commit -m "A parent with live children may idle, and may not answer"
```

- [ ] **Step 6: Mutation-check**

Make `build_registry` offer both tools unconditionally and confirm the `"submit_answer" not in` assertion fails. Then make `Idle.run` stop instead of failing when there are no live children, and confirm the `refused.ok is False` assertion fails.

---

### Task 4: Exhaustion idles instead of forcing an answer

**Files:**
- Modify: `ancalagon/session.py`
- Test: `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: `Idling` (Task 1), the registry rule (Task 3).

`_final_turn` forces `submit_answer` and `registry.get(SUBMIT)` raises when the tool is absent — which Task 3 guarantees while children are live. So a parent that exhausts its turns with live children must idle instead.

The session must not open a bus. The registry already encodes the fact: `submit_answer` absent means children were live when the attempt began. Use that.

- [ ] **Step 1: Write the failing test**

```python
def test_exhausting_turns_with_live_children_idles_rather_than_forcing_an_answer():
    registry = Registry([...])  # every tool except submit_answer, plus idle
    session = Session(spec=..., registry=registry, ...)  # budget of 1 turn

    outcome = session.run()

    assert outcome.kind is OutcomeKind.IDLING
    assert outcome.spent == Budget(turns=1, tool_calls=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_session_loop.py -k exhausting_turns_with_live -v`
Expected: FAIL with `KeyError: unknown tool submit_answer`.

- [ ] **Step 3: Implement**

```python
            if self.remaining.turns_exhausted:
                if SUBMIT not in self.registry.names():
                    return Idling(summary="turns exhausted while children ran", spent=self._spent())
                return self._final_turn()
```

- [ ] **Step 4: Run, verify, commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
git add -A && git commit -m "A parent out of turns with children still running idles"
```

- [ ] **Step 5: Mutation-check**

Remove the `SUBMIT not in` branch and confirm the test fails with `KeyError` rather than passing.

---

### Task 5: The supervisor wakes an idling parent

**Files:**
- Modify: `ancalagon/supervisor/supervisor.py`
- Test: `tests/unit/test_supervisor.py`, `tests/integration/test_scripted_escalation.py`

**Interfaces:**
- Consumes: `Bus.live_children`, `Bus.resumable_idle` (Task 2).

When an agent reaches a terminal status, its task's `parent_agent` names the agent to wake. Wake it if `resumable_idle(parent)` — which asks the history, not the latest status.

- [ ] **Step 1: Write the failing test**

Extend the supervisor's behaviour test with a fake spawner:

```python
def test_a_child_finishing_re_enqueues_its_idling_parent(tmp_path: pathlib.Path):
    ...
    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)
    supervisor.tick()          # reaps the child, which exits 0

    assert bus.state(child).status is AgentStatus.EXITED
    resumed = [s for s in bus.live() if s.dir == str(parent_dir)]
    assert len(resumed) == 1
    assert resumed[0].agent != parent
```

Assert the *new* agent id differs from the old one — that is what proves a fresh attempt against the same task rather than a mutated row.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_supervisor.py -k idling_parent -v`
Expected: FAIL — nothing re-enqueues, so `resumed` is empty.

- [ ] **Step 3: Implement in `_finish`**

`_finish` is where every terminal status is recorded, so the wake belongs there rather than in `_reap`:

```python
    def _finish(self, agent: int, status: AgentStatus, code: int, summary: str) -> None:
        self.bus.record(agent, status, EventSource.SUPERVISOR, exit_code=code, summary=summary)
        self.live.pop(agent, None)
        self.started.pop(agent, None)
        self._wake_parent(agent)
```

`_wake_parent` reads `self.bus.state(agent).parent_agent`, returns when it is `HUMAN`, and re-enqueues the parent's directory when `resumable_idle(parent)` and the parent is not already live or queued. Guard against re-enqueuing twice: a parent with two children finishing in the same tick would otherwise get two agents.

- [ ] **Step 4: Prove it end to end**

Extend `tests/integration/test_scripted_escalation.py` so its scripted root delegates, idles, and is resumed after the child completes — driving real worker subprocesses. Assert the root's task directory holds two agents and that the second one's transcript contains the first's messages.

- [ ] **Step 5: Run, verify, commit**

```bash
uv run python -m black . && uv run pyright
uv run python -m pytest tests/unit && uv run python -m pytest tests/integration
git add -A && git commit -m "A child finishing wakes the parent that was waiting for it"
```

- [ ] **Step 6: Mutation-check**

Replace `resumable_idle(parent)` with a latest-status check (`self.bus.state(parent).status is AgentStatus.IDLING`) and confirm the test fails — the supervisor records `exited` after the worker's `idling`, so a latest-status check never fires. Then remove the already-live guard and confirm a parent with two children finishing in one tick gets two agents.

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Read both documents end to end before editing**

A grep finds dead identifiers; it cannot find a true-sounding sentence describing behaviour that no longer exists. Both documents describe delegation and `check_task` as the only way a parent learns anything.

- [ ] **Step 2: Write what changed**

Cover: `idle` and when it is offered; that `submit_answer` is withheld while children are live and what that removes (a parent can no longer abandon a child); that an idling attempt ends and is resumed as a new agent against the same task; that **a role's `budget` is granted per attempt, so a parent with three children may consume four budgets**; that a parent whose children finish mid-attempt idles once more before it can answer; and that schema version 4 means existing run databases need `ancalagon migrate`.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "Document idling, and the budget it costs"
```

---

## Self-Review

**Spec coverage.** `Idling` kind and status → Task 1. Wake condition derived from `tasks.parent_agent` → Task 2. `idle`, argument-free, refusing with no live children → Task 3. `submit_answer` withheld while children are live → Task 3. Exhaustion idling rather than forcing → Task 4. Supervisor waking on every child completion → Task 5. Budget-per-attempt consequence → Task 6.

**Two things left for the implementer to settle, flagged rather than guessed:**

1. Whether `resumable_idle` needs to scope to events after the last `queued` (Task 2, Step 3). It depends on whether an agent id can be reused across attempts. `enqueue` appears to insert a new agent row per attempt, which makes scoping unnecessary — but that must be read, not assumed.
2. How `build_registry` gets a bus (Task 3, Step 3). It has neither today, and the worker already holds one; passing it is preferable to opening a second connection, but the signature change touches every caller.

**Known and accepted:** a registry built once per attempt means children finishing mid-attempt cost one extra wake. Fixing it means rebuilding the tool list per turn, which is a larger change than this plan carries.

**Type consistency.** `Idling(kind, summary, spent)`, `Idled(waiting_for: tuple[int, ...])`, `Bus.live_children(agent) -> list[AgentState]`, `Bus.resumable_idle(agent) -> bool`, and the `idle` tool name are used identically in every task that mentions them.
