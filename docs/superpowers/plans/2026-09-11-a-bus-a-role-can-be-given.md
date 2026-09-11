# A Bus A Role Can Be Given Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the bus a declared protocol and a null object, and give `enqueue` a return type that can express "nothing was queued".

**Architecture:** A `Bus` protocol of the three methods the five bus-using tools actually call, which `LifecycleStore` inherits. `enqueue` stops returning a bare `int` and returns `AgentRef | NoAgentRef`, so a bus that queues nothing has something honest to hand back and the type checker forces every caller to handle it. `NoBus` is the null implementation.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-09-11-a-bus-a-role-can-be-given-design.md`

## Deviation from the spec, decided before writing this plan

The spec names an alias, `Enqueued = AgentRef | NoAgentRef`. **This plan drops the alias** and spells `AgentRef | NoAgentRef` in the four signatures that need it.

Reason: `ancalagon/attempt/queued.py` already defines `Queued`, a member of the `Attempt` union and a lifecycle state. `Enqueued` sits one letter from it and means something different — a return value, not a state. Two near-identical names for unrelated concepts in the same subsystem is a worse cost than repeating a two-member union four times. The repo aliases unions that appear dozens of times (`Outcome`, `Attempt`, `Allowance`); this one appears four times.

Specs are immutable, so the spec still reads `Enqueued`. This paragraph is the record of why the code does not.

## Global Constraints

- Pyright strict, ZERO errors. `Any` is banned outright — no `typing.Any`, no `dict[str, Any]`, no `object` annotations, no hand-rolled JSON aliases.
- Every generic parameterised: `dict[str, int]` not `dict`; `Sequence`, `Mapping`, `tuple` equally.
- NO COMMENTS except a single one-line header at the top of each module or class. No docstrings on functions, no inline explanations, no section dividers, no TODOs.
- All pydantic models `frozen=True`. Fully qualified imports, no relative imports. One class per file. No static methods.
- A class implementing a Protocol **inherits** it.
- No defensive programming: no `None` checks masking bugs, no bare `try/except`, no workaround guards. No `None` defaults, no `None` returns from non-`None` return types — use the null object pattern.
- No `for` loops that mutate an accumulator; comprehensions, `map`, `filter` instead.
- python-fp-lint forbids `list.append(...)` and caps cyclomatic complexity at 3 per function. It also enforces import ordering — after editing imports run `uv run ruff check --select I --fix ancalagon/ tests/`.
- Text is a boundary, never a carrier. Do not encode information in string representations; use typed objects and `isinstance`/`match`, never string prefixes or regex to deduce what a value is.
- Tests: few tests, each covering a whole behaviour, with concrete value assertions — never `assert x is not None` where a concrete value is available.
- No mocking (`unittest.mock` banned). Use the injected fakes: `FakeFileSystem`, `FakeClock`.
- Assertions are sacred: do not weaken or delete an existing assertion. If one now fails, that is a finding to report, not something to edit away.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`. Run the FULL integration suite on every task — it takes about 70 seconds. A previous plan in this repo shipped a regression precisely because a task skipped it.
- Do NOT use `python -c` with multiline strings. Write a script into the scratchpad and run `uv run python <path>`.
- Talisman may flag markdown prose as a false-positive secret. Reword when the wording is incidental; otherwise APPEND a `.talismanrc` entry for a newly flagged file, or REPLACE THE CHECKSUM IN PLACE for one already listed. Never duplicate a filename. Use the checksum Talisman reports, never one from `shasum`.

---

### Task 1: An id that can be absent

**Files:**
- Create: `ancalagon/contracts/agent_ref.py`
- Create: `ancalagon/contracts/no_agent_ref.py`
- Modify: `ancalagon/bus/lifecycle_store.py:162-174` — `enqueue` returns `AgentRef`
- Modify: `ancalagon/tools/delegate/delegate_to.py:67-68`
- Modify: `ancalagon/tools/watch/watch_file.py:70-73`
- Modify: `ancalagon/answer.py:45-70` — returns the union
- Modify: `ancalagon/answer_command.py:12-15` — unwraps at the CLI boundary
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `AgentRef(id: int)`, frozen, in `ancalagon/contracts/agent_ref.py`
  - `NoAgentRef()`, frozen, no fields, in `ancalagon/contracts/no_agent_ref.py`
  - `LifecycleStore.enqueue(dir, parent_agent) -> AgentRef`
  - `answer_task(...) -> AgentRef | NoAgentRef`

Task 2 relies on `enqueue`'s declared return type being `AgentRef | NoAgentRef` on the protocol, while `LifecycleStore`'s own annotation stays the narrower `AgentRef`. A narrower return satisfies a wider declared one, so the inheritance in Task 2 type-checks.

- [ ] **Step 1: Write the failing test**

Extend the existing test in `tests/unit/test_bus.py` at line 43. It currently reads:

```python
    first = bus.enqueue(alpha, parent_agent=0)
    second = bus.enqueue(tmp_path / "tasks" / "beta", parent_agent=first)
```

`first` is used six more times below as a bare int — `parent_agent=first`, `bus.attempt(first)`, `[first, second]` and so on. Do NOT convert all of those. **Unwrap at the assignment**, so one line asserts the new contract and every later line is untouched:

```python
    queued = bus.enqueue(alpha, parent_agent=0)

    assert queued == AgentRef(id=1)

    first = queued.id
    second = bus.enqueue(tmp_path / "tasks" / "beta", parent_agent=first).id
```

Everything after that in the test is unchanged. Add the import:

```python
from ancalagon.contracts.agent_ref import AgentRef
```

The literal `1` is the first agent id a fresh SQLite database issues, and this test builds one per run under `tmp_path`. If the test reports a different number, pin the number it actually reports — do not replace the assertion with a weaker one.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.contracts.agent_ref'`

- [ ] **Step 3: Create the two types**

`ancalagon/contracts/agent_ref.py`:

```python
# Which agent a bus queued, as a value rather than a bare number.
import pydantic


class AgentRef(pydantic.BaseModel, frozen=True):
    id: int
```

`ancalagon/contracts/no_agent_ref.py`:

```python
# What a bus that queues nothing hands back, so absence needs no sentinel number.
import pydantic


class NoAgentRef(pydantic.BaseModel, frozen=True): ...
```

- [ ] **Step 4: Wrap what `enqueue` returns**

In `ancalagon/bus/lifecycle_store.py`, change `enqueue`'s signature and its final statement:

```python
    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> AgentRef:
```

```python
        self.conn.execute("COMMIT")
        return AgentRef(id=agent_id)
```

Everything between stays as it is. Add `from ancalagon.contracts.agent_ref import AgentRef` in its alphabetical position.

- [ ] **Step 5: Handle the union at the two tool call sites**

`ancalagon/tools/delegate/delegate_to.py`, replacing lines 67-68:

```python
        match bus.enqueue(task_dir, parent_agent=self.parent):
            case AgentRef(id=agent):
                return ctx.result(
                    self.name, f"queued agent {agent} for task {args.task_id} at {task_dir}"
                )
            case NoAgentRef():
                return ctx.failure(
                    self.name, f"cannot queue task {args.task_id}: this session has no bus"
                )
```

`ancalagon/tools/watch/watch_file.py`, replacing lines 70-73:

```python
        match bus.enqueue(task_dir, parent_agent=self.parent):
            case AgentRef(id=agent):
                return ctx.result(
                    self.name, f"queued agent {agent} watching {watched} for changes after {seen}"
                )
            case NoAgentRef():
                return ctx.failure(
                    self.name, f"cannot watch {watched}: this session has no bus"
                )
```

Both files import both types. Note that `AgentRef(id=agent)` in a `case` is a pydantic model pattern-match that binds the field — it needs no `__match_args__` because keyword patterns work on any class with that attribute.

The `NoAgentRef` arm is unreachable today: `LifecycleStore.enqueue` always returns `AgentRef`, and these tools open a real `LifecycleStore`. It becomes reachable in the next spec, which injects the bus. Do not delete it as dead code — the whole point of the union is that the checker demands it now.

- [ ] **Step 6: Propagate the union through `answer_task`**

In `ancalagon/answer.py`, change the return annotation on `answer_task` (line ~52) from `int` to `AgentRef | NoAgentRef` and add both imports. Its body already ends `return bus.enqueue(...)`, so nothing else changes.

In `ancalagon/answer_command.py`, unwrap it for the message:

```python
def answer_command(run_dir: pathlib.PurePath, agent: int, answer: str) -> int:
    resumed = answer_task(
        run_dir, agent, answer, answered_by=HUMAN, clock=SystemClock(), fs=RealFileSystem()
    )
    match resumed:
        case AgentRef(id=queued):
            sys.stdout.write(f"answered agent {agent}; queued agent {queued}\n")
        case NoAgentRef():
            sys.stdout.write(f"answered agent {agent}; nothing was queued\n")
    return 0
```

- [ ] **Step 7: Run the tests**

```bash
uv run python -m pytest tests/unit -v
```
Expected: PASS. If a test outside `test_bus.py` fails because it compared `enqueue`'s result to an int, that is a real call site the union has surfaced — fix the test to use `AgentRef(id=n)` or `.id`, and report it in your report. Do not change what it asserts about the run, only how it names the value.

- [ ] **Step 8: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `lifecycle_store.py`, return `AgentRef(id=0)` instead of `AgentRef(id=agent_id)` — the extended `test_bus.py` assertion must fail.
2. In `delegate_to.py`, swap the two `case` arms' bodies so a successful enqueue reports a failure — a delegate test in `tests/unit/test_tools.py` must fail.

Restore both. If break 2 does not fail any test, say so in your report rather than inventing a test to make it fail.

- [ ] **Step 9: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 10: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Let a queued agent be a value instead of a number

enqueue returned a bare id, so a bus with nothing to queue had no honest
answer: zero would tell a model it had queued agent zero, and its next
check_task would find nothing there.

The id is now an AgentRef, and its absence a NoAgentRef, so the checker
makes every caller say what it does when nothing was queued.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: A bus a tool could be handed

**Files:**
- Create: `ancalagon/bus/bus.py`
- Create: `ancalagon/bus/no_bus.py`
- Modify: `ancalagon/bus/lifecycle_store.py:96` — `LifecycleStore` inherits `Bus`
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `AgentRef`, `NoAgentRef` from Task 1.
- Produces:
  - `Bus` protocol with `snapshot()`, `record(...)`, `enqueue(...)` in `ancalagon/bus/bus.py`
  - `NoBus` and the module constant `NO_BUS` in `ancalagon/bus/no_bus.py`

**Why three methods and not nine.** These are what the five bus-using tools call, measured rather than assumed: `idle` uses `snapshot`; `check_task` uses `snapshot`; `collect_task` uses `snapshot` and `record`; `delegate_to` uses `snapshot` and `enqueue`; `watch_file` uses `snapshot` and `enqueue`. The other six methods — `claim`, `dir_of`, `attempt`, `queued_count`, `history`, `task` — belong to the supervisor and the CLI commands, which hold a concrete `LifecycleStore`. Do not widen the protocol.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_bus.py`:

```python
def test_a_bus_that_queues_nothing_reports_an_empty_run_and_records_no_event():
    bus = NO_BUS
    snapshot = bus.snapshot()

    assert snapshot.tasks == ()
    assert dict(snapshot.agents_by_task) == {}
    assert dict(snapshot.task_by_agent) == {}
    assert dict(snapshot.events) == {}
    assert dict(snapshot.attempts) == {}

    assert bus.record(1, AgentStatus.QUEUED, EventSource.WORKER) is None
    assert bus.enqueue(pathlib.PurePath("/tmp/nowhere"), parent_agent=0) == NoAgentRef()
    assert bus.snapshot() == snapshot
```

The last line is the point: recording and enqueueing changed nothing, so the snapshot is what it was. Add the imports the test needs — `pathlib`, `AgentStatus`, `EventSource`, `NoAgentRef`, and `NO_BUS` — in their alphabetical positions.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.bus.no_bus'`

- [ ] **Step 3: Declare the protocol**

`ancalagon/bus/bus.py`:

```python
# What a tool needs of a bus: read the run, record what happened, queue a task.
import pathlib
import typing

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_ref import AgentRef
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.no_agent_ref import NoAgentRef


class Bus(typing.Protocol):
    def snapshot(self) -> Snapshot: ...

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
        seen_through: int = 0,
    ) -> None: ...

    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> AgentRef | NoAgentRef: ...
```

Check the real import paths for `AgentStatus` and `EventSource` before writing this — read the top of `ancalagon/bus/lifecycle_store.py`, which imports both.

- [ ] **Step 4: Make `LifecycleStore` say it is one**

In `ancalagon/bus/lifecycle_store.py`, change the class line:

```python
class LifecycleStore(Bus):
```

and add `from ancalagon.bus.bus import Bus`.

Its `enqueue` keeps the narrower `-> AgentRef` annotation from Task 1. A narrower return satisfies a wider declared one, so this type-checks. If Pyright disagrees on any of the three methods, the signature genuinely differs — report the exact error rather than widening the annotation to silence it.

- [ ] **Step 5: Write the null object**

`ancalagon/bus/no_bus.py`:

```python
# The bus an agent has when it runs alone: nothing to read, nothing to queue.
import pathlib

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.bus import Bus
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.no_agent_ref import NoAgentRef

EMPTY = Snapshot(tasks=(), agents_by_task={}, task_by_agent={}, events={}, attempts={})


class NoBus(Bus):
    def snapshot(self) -> Snapshot:
        return EMPTY

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
        seen_through: int = 0,
    ) -> None:
        return None

    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> NoAgentRef:
        return NoAgentRef()


NO_BUS = NoBus()
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_bus.py -v`
Expected: PASS.

- [ ] **Step 7: Prove the inheritance catches a real mistake**

This is the reason `LifecycleStore` inherits rather than matching structurally, so confirm it works. Temporarily rename `LifecycleStore.snapshot` to `snapshot_of`, run `uv run pyright`, and confirm the error names `LifecycleStore` — not some distant call site. Paste the error into your report, then restore the name.

- [ ] **Step 8: Mutation-check**

Break the code two ways and confirm the new test fails each time:

1. In `no_bus.py`, make `enqueue` return `AgentRef(id=0)` instead of `NoAgentRef()`.
2. In `no_bus.py`, make `record` append to a module-level list and have `snapshot` reflect it, so the final `bus.snapshot() == snapshot` assertion breaks.

Restore both. For break 2, if making `record` observable takes more than a couple of lines, do the simpler equivalent: have `snapshot` return a non-empty `Snapshot` and confirm the first assertion block fails.

- [ ] **Step 9: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

`lint-imports` matters here: `ancalagon.bus` sits above `ancalagon.attempt` and `ancalagon.contracts` in the layer contract, and `bus.py` imports from both, which is downward and therefore legal. If a contract breaks, report the exact contract name rather than editing `pyproject.toml`.

- [ ] **Step 10: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Give the bus a shape a tool can be handed

Five tools open a database nobody gave them, so nothing reading the
registry can tell which of them touch the bus. This is the protocol they
would be handed: the three methods they actually call, no more.

NoBus has no caller yet. Injecting it is the next change; this one is
the type it will be injected as.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- The spec is `docs/superpowers/specs/2026-09-11-a-bus-a-role-can-be-given-design.md`. Read it before Task 1. It records why `enqueue` returns a union rather than raising, so you do not re-propose the alternative.
- **This plan drops the spec's `Enqueued` alias on purpose.** See the deviation note at the top. Write `AgentRef | NoAgentRef` in full.
- `NoBus` ends this plan with no production caller, and that is intended. The next spec injects it. Do not add a caller to justify it, and do not delete the `NoAgentRef` match arms as unreachable — the checker demands them and the next change makes them live.
- Do not widen the `Bus` protocol beyond three methods, and do not change `LifecycleStore`'s behaviour, schema, or other six methods.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
