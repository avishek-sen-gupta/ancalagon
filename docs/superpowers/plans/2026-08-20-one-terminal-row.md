# One Terminal Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each store one writer for an agent's ending — the worker writes `outcome.json`, the supervisor writes one terminal row — so the gaps between three writers stop producing bugs.

**Architecture:** The worker stops recording its own verdict to the bus. The supervisor stops writing `outcome.json`. When the supervisor closes an agent it reads the outcome file: present means the worker spoke, so it records that outcome's `kind`; absent means it did not, so it records `crashed` or `timed_out`. `Closed` therefore means an answer exists on disk and `Lost` means it does not, which lets `collect_task` read the bus instead of the filesystem and lets an adopted process be reaped like a spawned one.

**Tech Stack:** Python 3.13, Pydantic v2, SQLite (stdlib), pytest, Pyright strict.

**Spec:** `docs/superpowers/specs/2026-08-20-one-terminal-row-design.md`

## Global Constraints

- Pyright strict, **zero errors**. `Any` banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and hand-rolled recursive JSON types banned for the same reason.
- Every generic parameterised: `list[AgentEvent]`, never bare `list`. `Sequence`/`Mapping`/`Collection` from `collections.abc` for parameters that are not mutated.
- **No comments** except a one-line header on a class or module. No docstrings, no inline explanations, no section dividers, no TODOs.
- All Pydantic models `frozen=True`. **One class per file.** Fully qualified imports, no relative imports.
- A class implementing a `Protocol` **inherits** it. The exception is `Process`, which is the shape of `subprocess.Popen` and stays structural.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance` on our own types, no bare `except`, no workaround guards. Use a null object or a distinct type instead.
- **Never ask an agent's *latest* status what happened to it.** Statuses are appended, never replaced. Ask the fold — `Bus.attempt(agent)`.
- **Never ask an *agent* a question about a *task*.** `tasks.parent_agent` is written only when the task row is new. `collect_task` conflated these as recently as commit `873b849`.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file. Concrete assertions, never `assert x is not None`.
- **No mocking.** `unittest.mock.patch` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, `FakeProcess`, `FakeSpawner`, `FakeLiveness`.
- `001_init` is the only migration and is edited in place. Run directories are disposable; no backward compatibility is promised, and existing databases are **not** migrated.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`.
- **There is no bypass.** `--no-verify` and `git commit -n` are blocked by a `PreToolUse` hook. Do not look for another way to write the commit. If a hook fails, fix the cause, or stop and raise it — a commit that appears to need a bypass needs a decision instead.
- The `python-fp-lint` hook lints **staged content of staged files**, not merely your diff, so any file you touch is linted whole. `tests/` is excluded; production code is not. Task 0 clears `bus.py` and `supervisor.py`, so if you meet a violation in a file you touched, it is yours. **`pre-commit run --all-files` is NOT a substitute for checking — it passes this hook while the staged run fails it.** **Never `git stash`.**
- Never reference an external codebase in a tracked artifact.

---

## File Structure

**Created**
- `ancalagon/contracts/outcome_header.py` — `OutcomeHeader`, one field, so the supervisor can read an outcome's `kind` without resolving the role's answer class.
- `ancalagon/supervisor/adopted_process.py` — `AdoptedProcess`, a `Process` for a pid we did not spawn, backed by `Liveness`.

**Modified**
- `ancalagon/bus/bus.py`, `ancalagon/supervisor/supervisor.py` — cleared of `python-fp-lint` violations in Task 0, before any behaviour changes.
- `ancalagon/worker.py` — stops recording its own verdict; writes `outcome.json` on both paths.
- `ancalagon/supervisor/supervisor.py` — `_reap` and `_resolve_one` record the terminal row from the outcome file; `_write_outcome` and `_crashed` deleted; `_resolve_running` adopts.
- `ancalagon/attempt/next_state.py` — a supervisor-written verdict from `Running` yields `Closed`; the worker-verdict case goes.
- `ancalagon/bus/bus.py` — `unreaped` drops `Reported`.
- `ancalagon/tools/delegate/collect_task.py` — reads the bus, not the filesystem, to decide whether a child finished.
- `ancalagon/contracts/agent_status.py` — `EXITED` deleted.
- `ancalagon/contracts/outcome.py`, `outcome_kind.py` — `TimedOut` and `OutcomeKind.TIMED_OUT` deleted.
- `ancalagon/migrations/001_init.up.sql` — `'exited'` removed from the status `CHECK`.
- `README.md`, `docs/architecture.md`.

**Deleted**
- `ancalagon/attempt/reported.py`
- `ancalagon/contracts/timed_out.py`

---

### Task 0: Clear the lint debt in the two files every later task touches

**Files:**
- Modify: `ancalagon/bus/bus.py`, `ancalagon/supervisor/supervisor.py`

**Interfaces:**
- Produces: `Bus.enqueue` and `Supervisor._start_queued` with unchanged signatures and unchanged observable behaviour. This task changes nothing a test can see, except one query count noted below.

`python-fp-lint` lints the whole staged content of any file you touch, and there is no bypass. `bus.py` and `supervisor.py` carry twenty violations between them, so without this task every later commit is blocked by debt it did not create. None of these are architectural: each has a fix that is an improvement.

- [ ] **Step 1: Replace the row-to-dict comprehensions**

Seven sites in `bus.py` write `{k: r[k] for k in r.keys()}`, which only converts a `sqlite3.Row` into a `dict` — no mapping, no transformation. `dict(r)` does the same thing and Pyright strict accepts it.

Do **not** apply what `SIM118` literally suggests. `for k in r` iterates a `Row`'s **values**, not its keys, so that "fix" silently builds a dict keyed by values. Confirm it yourself before starting:

```bash
uv run python -c "
import sqlite3
c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
r=c.execute('select 1 as a, 2 as b').fetchone()
print(list(r), list(r.keys()), dict(r))
"
```

Six of the seven become `dict(r)` or `dict(row)` directly — `bus.py:72,183,205,258,264,287`. The seventh, in `tokens_by_agent` at `bus.py:298`, filters a key:

```python
            int(r["agent"]): CallUsage.model_validate(
                {k: v for k, v in dict(r).items() if k != "agent"}
            )
```

- [ ] **Step 2: Make `enqueue` find-or-create in one statement**

`bus.py:118-123` selects, tests `is None`, then inserts and reassigns `task` — reported as both `no-is-none` and `reassignment`. `tasks.dir` is `NOT NULL UNIQUE`, so one upsert returns the id whether or not the row existed:

```python
        task = self.conn.execute(
            "INSERT INTO tasks (dir, parent_agent, created) VALUES (?, ?, ?) "
            "ON CONFLICT(dir) DO UPDATE SET dir = dir RETURNING id",
            (str(dir), parent_agent, self._now()),
        ).fetchone()
```

`DO UPDATE SET dir = dir` is a no-op write that makes `RETURNING` fire on the conflict path; `DO NOTHING` returns no row at all.

**Existing behaviour must hold: re-enqueuing an existing directory must not change its `parent_agent`.** A task keeps the parent it was created with across attempts, and there is already a test asserting it. Run that test and confirm it still passes — this is the one step in this task that could change behaviour.

- [ ] **Step 3: Replace the remaining `is None` guards with `match`**

`bus.py:262` and `supervisor.py:86`. The rule asks for structural pattern matching, which reads better here anyway:

```python
    def task(self, dir: pathlib.Path) -> TaskRow:
        match self.conn.execute("SELECT * FROM tasks WHERE dir = ?", (str(dir),)).fetchone():
            case None:
                raise KeyError(f"no task at {dir}")
            case row:
                return TaskRow.model_validate(dict(row))
```

- [ ] **Step 4: Claim once instead of once per free slot**

`supervisor.py:52-56` loops `for _ in range(free)` calling `self.bus.claim(limit=1)` each time — `free` queries where one suffices, and the source of the `no-loop-mutation` and `no-deep-nesting` reports. `claim` already takes a limit:

```python
    def _start_queued(self) -> None:
        free = self.max_concurrent - len(self.live)
        if free <= 0:
            return
        for state in self.bus.claim(limit=free):
            self._spawn(state)
```

Move the old loop body — the `try`/`except OSError`, the `running` record, and the `self.live`/`self.started` writes — into `_spawn(self, state: AgentState) -> None`. That extraction is what clears the nesting reports.

This changes how many times `claim` is called, which is an improvement rather than a regression: `claim` is atomic across its whole limit, so claiming `free` at once is also more correct when a second reader exists. If a test counts claims, update it to the true number.

- [ ] **Step 5: Stop mutating the live and started dicts in place**

`supervisor.py:68,69,173,174`. Assign rather than mutate:

```python
        self.live = {**self.live, state.agent: process}
        self.started = {**self.started, state.agent: self.clock.time()}
```

and in `shutdown`:

```python
    def shutdown(self) -> None:
        self.live = {}
        self.started = {}
```

`_finish` pops from both; rewrite it the same way:

```python
        self.live = {a: p for a, p in self.live.items() if a != agent}
        self.started = {a: s for a, s in self.started.items() if a != agent}
```

Both dicts hold at most `max_concurrent` entries, so copying costs nothing. `Supervisor` is still the imperative shell — it still carries mutable state across ticks; it just stops mutating containers in place.

- [ ] **Step 6: Extract the remaining nested branches**

`supervisor.py:84,106`. `_wake_idling`'s `for` with an `if ... continue` is a filter, so it becomes a comprehension:

```python
    def _wake_idling(self) -> None:
        asleep = [
            task
            for task in self.bus.wakeable()
            if self.bus.newest_agent(task.id) not in self.live
        ]
        for task in asleep:
            self.bus.enqueue(pathlib.Path(task.dir), parent_agent=task.parent_agent)
```

For `_reap`, extract the timeout branch into a helper so the loop body is flat. Task 4 rewrites `_reap` entirely, so keep this minimal and do not redesign it here.

- [ ] **Step 7: Verify the debt is gone**

The hook reports only on staged content, so stage first:

```bash
git add -A
pre-commit run python-fp-lint
```

Expected: Passed. If a violation remains in either file, fix it — do not leave it for a later task, and do not exclude the file.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git commit -m "Clear the lint debt in bus and supervisor"
```

This task must change no test expectation except a claim count, if one exists. If any other assertion needs changing, stop and report it — that means behaviour changed, and this task was meant to change none.

---

### Task 1: `OutcomeHeader`, so the supervisor can read a kind

**Files:**
- Create: `ancalagon/contracts/outcome_header.py`
- Test: `tests/unit/test_contracts.py`

**Interfaces:**
- Produces: `OutcomeHeader` with field `kind: OutcomeKind`, parsed via `OutcomeHeader.model_validate_json(text)`.

The supervisor must learn what kind of outcome a worker wrote. `collect_task` gets this by reading `spec.json`, resolving the role's answer class and building a `TypeAdapter` — far more than the supervisor needs, and it would drag contract resolution into the supervisor. A one-field model reads the discriminator and ignores the rest, which Pydantic does by default.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_contracts.py`:

```python
def test_an_outcome_header_reads_the_kind_from_any_outcome():
    completed = Completed[FreeText](
        value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=2)
    )
    assert (
        OutcomeHeader.model_validate_json(completed.model_dump_json()).kind
        == OutcomeKind.COMPLETED
    )

    failed = Failed(error="boom", summary="boom", spent=Budget(turns=0, tool_calls=0))
    assert OutcomeHeader.model_validate_json(failed.model_dump_json()).kind == OutcomeKind.FAILED
```

Import `OutcomeHeader` from `ancalagon.contracts.outcome_header`, and `Completed`, `Failed`, `FreeText`, `Budget`, `OutcomeKind` from their own modules.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_contracts.py -k outcome_header -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.contracts.outcome_header'`

- [ ] **Step 3: Write the model**

```python
# ancalagon/contracts/outcome_header.py
# An outcome read for its kind alone, without resolving the answer class it carries.
import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind


class OutcomeHeader(pydantic.BaseModel, frozen=True):
    kind: OutcomeKind
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_contracts.py -k outcome_header -v`
Expected: PASS

- [ ] **Step 5: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add -A
git commit -m "An outcome's kind can be read without its answer class"
```

---

### Task 2: `collect_task` asks the bus, not the filesystem

**Files:**
- Modify: `ancalagon/tools/delegate/collect_task.py`
- Test: `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `Bus.attempt(agent) -> Attempt`, `Closed(verdict: AgentStatus)`, `Lost(close: AgentStatus)`.

`collect_task` currently reads `outcome.json` to decide whether a child produced anything, and treats a missing file as "no outcome yet" whatever the bus says. That defect has been fixed twice — once for crashed workers, once for agents killed at startup — each time by teaching another death path to fabricate a file. Task 4 removes fabrication entirely, so this must move first or a `Lost` child becomes uncollectable.

After this task: a `Closed` child has an answer on disk and it is read; a `Lost` child has none and is reported from the row.

- [ ] **Step 1: Write the failing test**

Extend `test_collect_task_returns_a_typed_answer_and_explains_every_other_ending` in `tests/unit/test_tools.py`. Build a child that is `Lost`, delete any outcome file, and collect it:

```python
    lost = bus.enqueue(run_dir / "tasks" / "lost", parent_agent=parent)
    bus.record(lost, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(lost, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=7)
    bus.record(
        lost, AgentStatus.TIMED_OUT, EventSource.SUPERVISOR, summary="killed after 600s"
    )
    (run_dir / "tasks" / "lost" / "outcome.json").unlink(missing_ok=True)

    result = CollectTask(run_dir, FakeClock()).run(TaskArgs(task=lost), _ctx(tmp_path))
    assert result.ok is False
    assert result.summary.text_for_model() == "agent 3 ended as timed_out: killed after 600s"
    assert AgentStatus.COLLECTED in [e.status for e in bus.history(lost)]
```

Replace `3` with the agent id the fixture actually produces — assert the real value, do not loosen the assertion to a substring match.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_tools.py -k collect_task -v`
Expected: FAIL — the current code returns `"agent 3 is timed_out, no outcome yet"` because `outcome.json` is missing.

- [ ] **Step 3: Rewrite `run`**

Replace the body from the `newest` line through the `outcome_adapter` call:

```python
        newest = bus.newest_agent(state.task)
        attempt = bus.attempt(newest)
        if not isinstance(attempt, (Closed, Lost)):
            return ctx.failure(self.name, f"agent {newest} has not been closed yet")
        if not bus.outstanding(state.task):
            bus.record(newest, AgentStatus.COLLECTED, EventSource.WORKER)
        if isinstance(attempt, Lost):
            return ctx.failure(
                self.name,
                f"agent {newest} ended as {attempt.close.value}: "
                f"{bus.state(newest).summary}",
            )
        task_dir = pathlib.Path(state.dir)
        spec = TaskSpec.model_validate_json((task_dir / "spec.json").read_text())
        answer_class = resolve_class(spec.role.answer)
        outcome = outcome_adapter(answer_class).validate_json(
            (task_dir / "outcome.json").read_text()
        )
        if isinstance(outcome, (Completed, Exhausted)):
            return ctx.full_result(self.name, outcome.value.model_dump_json(), ".json")
        return ctx.failure(
            self.name, f"agent {newest} ended as {outcome.kind.value}: {_detail(outcome)}"
        )
```

Note that `COLLECTED` is recorded before the `Lost` branch returns, so both endings are recorded as read. `newest` is used for every agent-level operation and `state.task` for every task-level one.

- [ ] **Step 4: Run the suite**

Run: `uv run python -m pytest tests/unit tests/integration -q`
Expected: PASS. Other tests may need a `Lost` child's summary asserted; update expectations, never weaken an assertion.

- [ ] **Step 5: Mutation-check**

Make the `Lost` branch read `outcome.json` anyway; the new assertion must fail because the file does not exist. Restore.

- [ ] **Step 6: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "A child that never spoke is reported from the log, not the disk"
```

---

### Task 3: The transition table accepts a supervisor-written verdict

**Files:**
- Modify: `ancalagon/attempt/next_state.py`
- Test: `tests/unit/test_attempt.py`

**Interfaces:**
- Produces: `next_state(Running(), <verdict>, EventSource.SUPERVISOR, pid) -> Closed(verdict=<verdict>)`.

This is additive. The worker-written case stays for now so the suite remains green; Task 5 removes it once nothing writes it.

- [ ] **Step 1: Write the failing test**

Add to the existing `test_every_lifecycle_path_folds_to_the_state_it_describes` in `tests/unit/test_attempt.py`:

```python
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.RUNNING, S),
            (AgentStatus.COMPLETED, S),
        )
    ) == Closed(verdict=AgentStatus.COMPLETED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_attempt.py -v`
Expected: FAIL with `IllegalTransition: cannot record 'completed' from 'supervisor' on Running(pid=0)`

- [ ] **Step 3: Add the case**

In `next_state`, immediately after the `Claimed() -> Running` case and **before** the close cases:

```python
        case (Running(), spoken_status, EventSource.SUPERVISOR) if spoken_status in VERDICTS:
            return Closed(verdict=spoken_status)
```

Order matters: `VERDICTS` and `CLOSES` are disjoint, so this cannot shadow the `Lost` case, but placing it before them keeps the reading order verdict-then-close.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit -q`
Expected: PASS

- [ ] **Step 5: Mutation-check**

Change the new case to return `Lost(close=spoken_status)`; the new assertion must fail. Restore.

- [ ] **Step 6: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add -A
git commit -m "A supervisor may record the verdict a worker left behind"
```

---

### Task 4: One writer per store

**Files:**
- Modify: `ancalagon/worker.py:181-197`, `ancalagon/supervisor/supervisor.py`
- Test: `tests/unit/test_supervisor.py`, `tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: `OutcomeHeader` (Task 1), the supervisor-verdict transition (Task 3), `collect_task` reading the bus (Task 2).
- Produces: `Supervisor._close(agent: int, close: AgentStatus, summary: str) -> None`, and `Supervisor._finish(agent: int, status: AgentStatus, summary: str) -> None` with its `code` parameter removed.

**No terminal row records an exit code.** A process the supervisor spawned has one and an adopted process never will, so recording it would make adopted rows distinguishable from spawned ones for a value nothing reads — `exit_code` is consulted by three test assertions and by no production code. Dropping it is what makes the two genuinely uniform rather than uniform-except-one-column. The diagnostic is not lost: a worker's stderr is already captured per agent in `stderr-<agent>.log`, and the summary says what happened in terms the supervisor actually observed.

This is the core swap and it is indivisible: the worker's record and the supervisor's record cannot both exist, because a verdict recorded twice is an illegal transition.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_supervisor.py`:

```python
def test_the_supervisor_records_what_the_worker_left_and_never_writes_an_outcome(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    spoke_dir = tmp_path / "spoke"
    silent_dir = tmp_path / "silent"
    spoke_dir.mkdir()
    silent_dir.mkdir()
    (spoke_dir / "outcome.json").write_text(
        Completed[FreeText](
            value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=1)
        ).model_dump_json()
    )

    spoke = bus.enqueue(spoke_dir, parent_agent=HUMAN)
    silent = bus.enqueue(silent_dir, parent_agent=HUMAN)
    supervisor = Supervisor(
        bus=bus,
        spawner=FakeSpawner([(0, 0), (0, 1)]),
        max_concurrent=2,
        timeout_s=60,
        clock=FakeClock(),
    )
    supervisor.tick()
    supervisor.tick()

    assert bus.attempt(spoke) == Closed(verdict=AgentStatus.COMPLETED)
    assert bus.attempt(silent) == Lost(close=AgentStatus.CRASHED)
    assert (silent_dir / "outcome.json").exists() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_supervisor.py -k never_writes_an_outcome -v`
Expected: FAIL — the agent that spoke folds to `Lost(close=AgentStatus.EXITED)`, because the supervisor records from the exit code and ignores the file.

- [ ] **Step 3: Stop the worker recording its verdict**

In `ancalagon/worker.py`, delete the `bus.record(...)` call in the success path so it reads:

```python
        outcome = session.run()
        outcome_path.write_text(outcome.model_dump_json())
        return 0
```

Leave the `except` branch as it is — it already writes `outcome.json` and records nothing. Remove the now-unused `EventSource` and `AgentStatus` imports if nothing else in the file uses them; check with `grep -n "AgentStatus\|EventSource" ancalagon/worker.py` before deleting.

- [ ] **Step 4: Make the supervisor record from the file**

In `ancalagon/supervisor/supervisor.py`, delete `_write_outcome` and `_crashed`, and add:

```python
    def _close(self, agent: int, close: AgentStatus, summary: str) -> None:
        written = pathlib.Path(self.bus.state(agent).dir) / "outcome.json"
        if written.exists():
            spoken = OutcomeHeader.model_validate_json(written.read_text())
            self._finish(agent, AgentStatus(spoken.kind.value), summary)
            return
        self._finish(agent, close, summary)
```

Drop `_finish`'s `code` parameter so no terminal row writes an `exit_code`:

```python
    def _finish(self, agent: int, status: AgentStatus, summary: str) -> None:
        self.bus.record(agent, status, EventSource.SUPERVISOR, summary=summary)
        self.live.pop(agent, None)
        self.started.pop(agent, None)
```

Update its other caller, the spawn-failure branch of `_start_queued`, to
`self._finish(state.agent, AgentStatus.CRASHED, f"spawn failed: {exc}")`.

Rewrite `_reap`'s body. `poll()`'s value is tested for `None` and never otherwise used, which is exactly what makes an adopted process indistinguishable from a spawned one here:

```python
    def _reap(self) -> None:
        for agent, process in list(self.live.items()):
            if process.poll() is None:
                if self.clock.time() - self.started[agent] >= self.timeout_s:
                    LOGGER.warning("killing agent %s after %ss", agent, self.timeout_s)
                    process.kill()
                    self._close(agent, AgentStatus.TIMED_OUT, f"killed after {self.timeout_s}s")
                continue
            self._close(agent, AgentStatus.CRASHED, "no outcome written")
```

A worker that finished cleanly is now recorded by what it said, so the `EXITED`/`CRASHED` choice is gone: `CRASHED` is only the fallback when nothing was written, and the summary says that rather than quoting a code.

Rewrite `_resolve_one` to use the same rule:

```python
    def _resolve_one(self, agent: int) -> None:
        running = [e for e in self.bus.history(agent) if e.status is AgentStatus.RUNNING]
        if running and self.liveness.is_running(running[-1].pid):
            self._resolve_running(agent, running[-1])
            return
        self._close(agent, AgentStatus.CRASHED, "no live process at startup")
```

The `Reported` branch goes — a worker can no longer have reported without the supervisor having closed it. Remove the `Reported` import.

In `_resolve_running`, replace the `_write_outcome` call and the `bus.record` beneath it with:

```python
        self.liveness.kill(running.pid)
        self._close(agent, AgentStatus.TIMED_OUT, f"killed after {self.timeout_s}s at startup")
```

Delete the now-unused `Budget`, `Failed`, `Outcome` and `TimedOut` imports; check each with grep before removing.

- [ ] **Step 5: Run the suites and fix fixtures**

Run: `uv run python -m pytest tests/unit tests/integration -q`

Tests that recorded a worker verdict and then a supervisor close now write an illegal sequence. Update `settle` in `tests/unit/conftest.py`:

```python
def settle(bus: Bus, agent: int, verdict: AgentStatus, pid: int = 1) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(agent, verdict, EventSource.SUPERVISOR)
```

One row where there were two. **Do not exempt a test from enforcement and do not weaken an assertion to accommodate a fixture** — a fixture that cannot write a legal sequence is describing a run that cannot happen.

- [ ] **Step 6: Drop the `exit_code` assertions**

Three tests read `exit_code`, and no production code does: `tests/unit/test_supervisor.py:124,126` and `tests/integration/test_end_to_end.py:136`. Terminal rows no longer write it, so those assertions now compare against the column default and are trivially true.

Replace each with an assertion on what the row now means — the folded attempt, or the summary. For example, `assert bus.state(good).exit_code == 0` becomes `assert bus.attempt(good) == Closed(verdict=AgentStatus.COMPLETED)`, and `assert bus.state(bad).exit_code == 1` becomes `assert bus.attempt(bad) == Lost(close=AgentStatus.CRASHED)`. **Do not simply delete them** — each was pinning that the supervisor distinguished two endings, and that distinction still exists, in a better place.

- [ ] **Step 7: Pin the CLI's exit code**

`ancalagon/cli.py:155` returns 1 when the root produced no outcome. Until now the supervisor fabricated one, so a crashed root exited 0. Add to `tests/integration/test_end_to_end.py` an assertion that a run whose root worker dies without writing `outcome.json` exits 1 — extend the existing crash test rather than adding a file.

- [ ] **Step 8: Mutation-check**

Make `_close` ignore the file and always record its `close` argument; the `Closed(verdict=COMPLETED)` assertion must fail. Restore.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "One writer per store: the worker's outcome, the supervisor's row"
```

---

### Task 5: Delete what nothing writes

**Files:**
- Delete: `ancalagon/attempt/reported.py`, `ancalagon/contracts/timed_out.py`
- Modify: `ancalagon/attempt/attempt.py`, `ancalagon/attempt/next_state.py`, `ancalagon/bus/bus.py`, `ancalagon/contracts/agent_status.py`, `ancalagon/contracts/outcome.py`, `ancalagon/contracts/outcome_kind.py`, `ancalagon/migrations/001_init.up.sql`
- Test: `tests/unit/test_migrations.py`, `tests/unit/test_attempt.py`

**Interfaces:**
- Consumes: Task 4, which removed the last writer of a worker verdict, of `exited`, and of a `TimedOut` outcome.

- [ ] **Step 1: Write the failing test**

Extend `test_migrations_round_trip_and_checks_reject_bad_rows` in `tests/unit/test_migrations.py`:

```python
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO agent_events (agent, ts, status, source) "
            "VALUES (1, 't', 'exited', 'supervisor')"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_migrations.py -v`
Expected: FAIL — the insert succeeds, because `'exited'` is still in the `CHECK` list.

- [ ] **Step 3: Delete `Reported`**

Remove `ancalagon/attempt/reported.py`, its import and union member in `ancalagon/attempt/attempt.py`, and in `next_state.py` remove both the `Reported` import and the two cases mentioning it — `(Running(), worker_status, EventSource.WORKER)` and `(Reported(...), close_status, EventSource.SUPERVISOR)`.

In `ancalagon/bus/bus.py`, `unreaped` becomes:

```python
    def unreaped(self) -> list[AgentState]:
        return [
            state
            for state in self._states("ORDER BY a.id", ())
            if isinstance(self.attempt(state.agent), (Claimed, Running))
        ]
```

- [ ] **Step 4: Delete `EXITED` and `TimedOut`**

Remove `EXITED = "exited"` from `AgentStatus`, `AgentStatus.EXITED` from `CLOSES` in `next_state.py`, and `'exited'` from the status `CHECK` in `001_init.up.sql`.

Remove `ancalagon/contracts/timed_out.py`, the `TimedOut` member of the `Outcome` union and of `outcome_adapter` in `ancalagon/contracts/outcome.py`, and `TIMED_OUT = "timed_out"` from `OutcomeKind`.

`AgentStatus.TIMED_OUT` stays — it is a close status and remains one.

- [ ] **Step 5: Grep for stragglers**

```bash
grep -rn "Reported\|EXITED\|exited\|TimedOut\|OutcomeKind.TIMED_OUT" ancalagon tests README.md docs/architecture.md | grep -v __pycache__
```

Every surviving match must be `AgentStatus.TIMED_OUT`, the word "exited" inside a summary string, or prose that is still true. Report anything else.

- [ ] **Step 6: Verify, mutation-check, commit**

Run both suites. Then restore `EXITED` to `AgentStatus` and the `CHECK` and confirm the Step 1 assertion fails.

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "Reported, exited and TimedOut have no writer left"
```

---

### Task 6: Adoption

**Files:**
- Create: `ancalagon/supervisor/adopted_process.py`
- Modify: `ancalagon/supervisor/supervisor.py`
- Test: `tests/unit/test_supervisor.py`

**Interfaces:**
- Consumes: `Liveness.is_running(pid: int) -> bool`, `Liveness.kill(pid: int) -> None`, `Supervisor._close` (Task 4).
- Produces: `AdoptedProcess(pid: int, liveness: Liveness)` satisfying `Process`.

This is the bug that started the work: `_resolve_running` leaves a healthy in-timeout worker alone without adding it to `self.live`, so `_reap` never sees it and `run_until_idle` returns while it is still running. Its outcome is never recorded and its parent never wakes.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_supervisor.py`:

```python
def test_a_healthy_worker_left_by_a_previous_supervisor_is_adopted_and_reaped(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    task_dir = tmp_path / "adopted"
    task_dir.mkdir()
    agent = bus.enqueue(task_dir, parent_agent=HUMAN)
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)

    liveness = FakeLiveness(alive=frozenset({4242}))
    supervisor = Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=600,
        clock=FakeClock(),
        liveness=liveness,
    )
    supervisor.resolve_stale()
    assert bus.attempt(agent) == Running(pid=4242)
    assert agent in supervisor.live

    (task_dir / "outcome.json").write_text(
        Completed[FreeText](
            value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=1)
        ).model_dump_json()
    )
    supervisor.liveness = FakeLiveness(alive=frozenset())
    supervisor.tick()
    assert bus.attempt(agent) == Closed(verdict=AgentStatus.COMPLETED)
```

`FakeLiveness` is reassigned rather than mutated because it is frozen; if that reads badly, give `FakeLiveness` a second instance and construct a second `Supervisor` sharing the same `bus`, which is what a real restart does.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_supervisor.py -k adopted -v`
Expected: FAIL with `assert 1 in {}` — `_resolve_running` returned without adopting.

- [ ] **Step 3: Write `AdoptedProcess`**

```python
# ancalagon/supervisor/adopted_process.py
# A worker this supervisor did not spawn, watched through Liveness because it has no pipe.
from ancalagon.supervisor.liveness import Liveness

ENDED = -1


class AdoptedProcess:
    def __init__(self, pid: int, liveness: Liveness):
        self.pid = pid
        self.liveness = liveness

    def poll(self) -> int | None:
        return None if self.liveness.is_running(self.pid) else ENDED

    def kill(self) -> None:
        self.liveness.kill(self.pid)
```

`AdoptedProcess` does not inherit `Process`, matching `subprocess.Popen`, which is the one structural contract in this codebase.

`ENDED` is named for what it means here rather than as an exit code, because it is not one and is never read as one: after Task 4, `_reap` compares `poll()` to `None` and uses the value for nothing. Any non-`None` int would behave identically. It is `-1` only so that a value which escapes into a log cannot be mistaken for a clean exit.

- [ ] **Step 4: Adopt in `_resolve_running`**

Replace the bare `return` in the inside-timeout branch:

```python
    def _resolve_running(self, agent: int, running: AgentEvent) -> None:
        elapsed = (self.clock.now() - datetime.datetime.fromisoformat(running.ts)).total_seconds()
        if elapsed <= self.timeout_s:
            LOGGER.info("adopting agent %s running as pid %s", agent, running.pid)
            self.live[agent] = AdoptedProcess(running.pid, self.liveness)
            self.started[agent] = self.clock.time() - elapsed
            return
        self.liveness.kill(running.pid)
        self._close(agent, AgentStatus.TIMED_OUT, f"killed after {self.timeout_s}s at startup")
```

`self.started` is back-dated by the elapsed time so the adopted worker's timeout is measured from when it actually started, not from when it was adopted.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/unit tests/integration -q`
Expected: PASS. `run_until_idle` now loops while an adopted agent is live, which is the fix.

- [ ] **Step 6: Mutation-check**

Remove the `self.live[agent] = ...` line, leaving the back-dating; the `agent in supervisor.live` assertion must fail. Then restore it and remove the back-dating instead, setting `self.started[agent] = self.clock.time()`; write a second assertion proving an adopted worker already past its timeout is killed on the next tick rather than granted a fresh timeout, and confirm it fails without the back-dating.

- [ ] **Step 7: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add -A
git commit -m "A worker outliving its supervisor is adopted, not abandoned"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`, `docs/architecture.md`

- [ ] **Step 1: Read both documents end to end before editing**

A grep finds a dead identifier; it cannot find a true-sounding sentence describing behaviour that no longer exists. `docs/architecture.md` gained a "The lifecycle" section yesterday describing eight states, `source` as what separates verdicts from closes, and a worker that records its own verdict. All three are now wrong.

- [ ] **Step 2: Write what is true**

Cover: seven states, `Reported` gone; the worker writes `outcome.json` and records nothing about itself; the supervisor writes one terminal row carrying both that the process ended and what the worker said; `Closed` means an answer exists on disk and `Lost` means it does not; the status alone separates verdict from close, because `source` no longer varies for an agent's own lifecycle; `collect_task` reads the bus; a worker outliving its supervisor is adopted at the next startup; `exited` is no longer a status; `ancalagon run` exits 1 when the root produced no answer.

`docs/architecture.md` says "It never retries. A crash is reported; the parent decides." That is still true. Check it, keep it, do not rewrite it.

- [ ] **Step 3: Grep for what you missed**

```bash
grep -rn "exited\|Reported\|TimedOut\|source\|fabricat\|synthesis" README.md docs/architecture.md
```

Expected: no match describes behaviour that no longer exists. Report each surviving match and why you kept it.

- [ ] **Step 4: Verify and commit**

`uv run python -m pytest tests/unit -q` must still pass, and `git diff --stat` must show only the two documents.

```bash
git add -A
git commit -m "Document one writer per store"
```

---

## Self-Review

**Spec coverage.** Lint debt cleared so later tasks can commit → Task 0. Worker stops recording → Task 4. Supervisor stops writing outcomes → Task 4. Terminal row from the outcome file → Task 4. `Closed`/`Lost` invariant → Tasks 3, 4. `collect_task` reads the bus → Task 2. `Reported` deleted → Task 5. `exited` deleted → Task 5. `TimedOut` and `OutcomeKind.TIMED_OUT` deleted → Task 5. `unreaped` narrowed → Task 5. Adoption → Task 6. CLI exit code → Task 4, Step 6. Migration edited in place → Task 5. Docs → Task 7.

**Ordering.** Task 2 must precede Task 4, or removing fabrication makes a `Lost` child uncollectable. Task 3 must precede Task 4, or the supervisor's first verdict write is an illegal transition. Task 5 must follow Task 4, or deleting the worker-verdict case breaks a worker that still records. Task 6 depends on `_close` from Task 4.

**The one indivisible task.** Task 4 changes the worker and the supervisor together because a verdict recorded by both is an illegal transition — there is no green intermediate state. It is the largest task in the plan and the review after it matters most.

**Type consistency.** `OutcomeHeader.kind: OutcomeKind`, `Supervisor._close(agent: int, close: AgentStatus, summary: str) -> None`, `AdoptedProcess(pid: int, liveness: Liveness)`, `Bus.attempt(agent: int) -> Attempt`, `Closed(verdict: AgentStatus)`, `Lost(close: AgentStatus)`, `settle(bus, agent, verdict, pid=1)` are used identically wherever they appear.

**Known and accepted, from the spec:** a parent sees a child's verdict one tick later; the bus stops showing worker progress mid-run; existing run databases will not fold and are not migrated; two supervisors sharing one `bus.db` remain out of scope; `wakeable`/`_has_news` is still an N+1 per tick; a worker killed mid-write leaves an `outcome.json` that will not parse, which is unchanged by this work.
