# Handing A Tool Its Bus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop six tools opening a database nobody gave them, and make a tool handed `NO_BUS` degrade honestly instead of orphaning a task directory.

**Architecture:** `Bus` threads from `worker.main` through `build_registry` and `available_tools` into the six tools that need one, and the parameters that existed only to build a `LifecycleStore` are removed. The two tools that write before they enqueue get null counterparts chosen at construction — same name, same schema, no file system — so `available_tools` picks the tool instead of the tool picking a branch.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-09-12-handing-a-tool-its-bus-design.md`

## A discovery the spec did not anticipate

`DelegateTo` builds `name`, `description` and `args_model` in `__init__` (`delegate_to.py:32-48`), the last with a `pydantic.create_model` call that embeds the role's resolved input class. `NoDelegateTo` must present a byte-identical schema to the model, so that construction cannot be duplicated — the review rubric treats verbatim duplication of a logic block as a defect, and two copies would drift.

Task 2 therefore extracts it into `ancalagon/tools/delegate/delegating.py`, which both classes call. `NoWatchFile` needs no equivalent: `WatchFile`'s `name`, `description`, `cost` and `args_model` are plain class attributes, so `NoWatchFile` references them directly and they are provably identical.

## Global Constraints

- Pyright strict, ZERO errors. `Any` is banned outright — no `typing.Any`, no `dict[str, Any]`, no `object` annotations, no hand-rolled JSON aliases.
- Every generic parameterised: `dict[str, int]` not `dict`; `Sequence`, `Mapping`, `tuple` equally.
- NO COMMENTS except a single one-line header at the top of each module or class. No docstrings on functions, no inline explanations, no section dividers, no TODOs.
- All pydantic models `frozen=True`. Fully qualified imports, no relative imports. One class per file. No static methods.
- A class implementing a Protocol **inherits** it.
- No defensive programming: no `None` checks masking bugs, no bare `try/except`, no workaround guards. No `None` defaults, no `None` returns from non-`None` return types — use the null object pattern.
- No `for` loops that mutate an accumulator; comprehensions, `map`, `filter` instead.
- python-fp-lint forbids `list.append(...)` and caps cyclomatic complexity at 3 per function. It also enforces import ordering — after editing imports run `uv run ruff check --select I --fix ancalagon/ tests/`.
- A constraint belongs on the args-model field where the tool schema shows it to the model, never as a hand-rolled check inside `run`.
- Do not encode information in string representations; use typed objects and `match`, never string prefixes or regex to deduce what a value is.
- Tests: few tests, each covering a whole behaviour, with concrete value assertions — never `assert x is not None` where a concrete value is available.
- No mocking (`unittest.mock` banned). `NO_BUS` is the injected fake; that is what it was built for.
- Assertions are sacred: do not weaken or delete an existing assertion. If one now fails, that is a finding to report.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`. Run the FULL integration suite on every task — about 70 seconds. An earlier plan in this repo shipped a regression because a task skipped it.
- Do NOT use `python -c` with multiline strings. Write a script into the scratchpad and run `uv run python <path>`.
- Talisman may flag markdown prose as a false-positive secret. Reword when the wording is incidental; otherwise APPEND a `.talismanrc` entry for a newly flagged file, or REPLACE THE CHECKSUM IN PLACE for one already listed. Never duplicate a filename. Use the checksum Talisman reports.

---

### Task 1: Hand each tool its bus

**Files:**
- Modify: `ancalagon/tools/delegate/check_task.py` — constructor becomes `(bus)`
- Modify: `ancalagon/tools/delegate/collect_task.py` — constructor becomes `(bus, fs)`; helpers at lines 70, 83, 102 widen to `Bus`
- Modify: `ancalagon/tools/idle/idle.py` — constructor becomes `(bus, agent)`
- Modify: `ancalagon/tools/delegate/delegate_to.py` — constructor becomes `(bus, role_name, role, run_dir, parent, fs)`
- Modify: `ancalagon/tools/watch/watch_file.py` — constructor becomes `(bus, role, run_dir, parent, fs)`
- Modify: `ancalagon/tools/delegate/answer_task.py` — constructor becomes `(bus, parent, clock, fs)`
- Modify: `ancalagon/tools/delegate/delegate_tools.py` — takes `bus`, drops `clock`
- Modify: `ancalagon/children/bus_children.py:9` — annotation widens to `Bus`
- Modify: `ancalagon/worker.py:80-88` (`available_tools`), `:125-133` (`build_registry`), `:149` (`WatchFile`), and the `build_registry` call in `main`
- Test: `tests/unit/test_tools.py`, plus every test that constructs one of the six

**Interfaces:**
- Consumes: `Bus` from `ancalagon/bus/bus.py`; `NO_BUS` from `ancalagon/bus/no_bus.py`; `AgentRef`/`NoAgentRef` from `ancalagon/contracts/`.
- Produces:
  - `available_tools(role, roles, run_dir, parent, output_class, clock, fs, web, bus) -> list[BoundTool]`
  - `build_registry(config, spec, run_dir, parent, depth, output_class, clock, fs, web, bus) -> Registry`
  - `delegate_tools(roles, caller, run_dir, parent, fs, bus) -> list[BoundTool]`
  - the six constructors above

`answer_task` the TOOL takes a `bus` here and keeps `clock` and `fs`, because it passes them to `ancalagon/answer.py`, which still opens its own bus until Task 3. Do not change `answer.py` in this task.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_tools.py`. One test covers the four tools that need no null variant, because they share the behaviour — an empty snapshot and a clean refusal.

```python
def test_the_four_bus_reading_tools_refuse_cleanly_when_there_is_no_bus(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)

    checked = CheckTask(NO_BUS).run(TaskArgs(task=7), ctx)
    collected = CollectTask(NO_BUS, RealFileSystem()).run(TaskArgs(task=7), ctx)

    assert checked.ok is False
    assert checked.error == "no agent 7"
    assert collected.ok is False
    assert collected.error == "no agent 7"

    idled = Idle(NO_BUS, agent=1).run(IdleArgs(), ctx)

    assert idled.ok is True
```

Read each tool's `run` before pinning those strings — `check_task.py` and `collect_task.py` both build the message from `args.task`, and `idle.py`'s success path returns a result whose text you should assert concretely rather than only `ok`. If `IdleArgs` takes fields, supply them. Correct the expected values against what the code really produces; do not loosen the assertions.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_tools.py -k no_bus -v`
Expected: FAIL — `CheckTask.__init__() takes 4 positional arguments but 2 were given`, or a `NameError` on `NO_BUS` until you add the import.

- [ ] **Step 3: Change the four simple constructors**

`check_task.py` — replace the whole `__init__` with:

```python
    def __init__(self, bus: Bus):
        self.bus = bus
```

and in `run`, replace the `bus = LifecycleStore.open(...)` line with `snapshot = self.bus.snapshot()`, deleting the now-unused local. Remove the `LifecycleStore`, `Clock` and `FileSystem` imports if nothing else in the file uses them.

`collect_task.py`:

```python
    def __init__(self, bus: Bus, fs: FileSystem):
        self.bus = bus
        self.fs = fs
```

Same treatment in `run`. Its helpers at lines 70, 83 and 102 annotate `bus: LifecycleStore` — widen each to `bus: Bus`.

`idle.py`:

```python
    def __init__(self, bus: Bus, agent: int):
        self.bus = bus
        self.agent = agent
```

`answer_task.py`:

```python
    def __init__(self, bus: Bus, parent: int, clock: Clock, fs: FileSystem):
        self.bus = bus
        self.parent = parent
        self.clock = clock
        self.fs = fs
```

`AnswerTask` does not yet use `self.bus` — `answer.py` still opens its own until Task 3. Store it anyway; Pyright's unused-attribute rules do not flag a stored constructor argument. If `reportUnusedVariable` does complain, report it rather than deleting the parameter.

- [ ] **Step 4: Change the two writing constructors**

`delegate_to.py` — `bus` first, `clock` gone:

```python
    def __init__(
        self,
        bus: Bus,
        role_name: str,
        role: Role,
        run_dir: pathlib.PurePath,
        parent: int,
        fs: FileSystem,
    ):
        self.bus = bus
```

with the rest of the body unchanged except that `self.clock = clock` goes. In `run`, delete the `bus = LifecycleStore.open(...)` line and use `self.bus` throughout.

`watch_file.py` — the same shape:

```python
    def __init__(
        self,
        bus: Bus,
        role: Role,
        run_dir: pathlib.PurePath,
        parent: int,
        fs: FileSystem,
    ):
```

Neither tool's behaviour under a real bus changes. Do not touch the order of the `mkdir` / `write_text` / `enqueue` sequence in this task — Task 2 makes it moot.

- [ ] **Step 5: Thread it through**

`delegate_tools.py`:

```python
def delegate_tools(
    roles: collections.abc.Mapping[str, Role],
    caller: Role,
    run_dir: pathlib.PurePath,
    parent: int,
    fs: FileSystem,
    bus: Bus,
) -> list[BoundTool]:
    return [
        bound_for(DelegateTo(bus, name, role, run_dir, parent, fs), caller)
        for name, role in roles.items()
    ]
```

`ancalagon/worker.py` — `available_tools` and `build_registry` each gain `bus: Bus` as the last parameter, and every construction inside `available_tools` updates to the new signatures. The `WatchFile` construction at line 149 is inside `build_registry`, so it uses that function's `bus`.

`main` already holds one at `worker.py:186`:

```python
    bus = LifecycleStore(conn, clock)
```

Pass it to `build_registry`. `depth_of(bus.snapshot(), agent_id)` at line 222 is unaffected.

`ancalagon/children/bus_children.py:9` — widen the `__init__` annotation from `LifecycleStore` to `Bus`.

- [ ] **Step 6: Fix every call site**

Find them rather than trusting a count:

```bash
grep -rn "build_registry(\|delegate_tools(\|CheckTask(\|CollectTask(\|Idle(\|AnswerTask(\|WatchFile(\|DelegateTo(" ancalagon tests --include="*.py" | grep -v pycache
```

There are 11 `build_registry` calls across 7 files and about 22 direct tool constructions in tests. Every test that builds a registry passes a real `LifecycleStore` — the one it already opens, or one opened from the test's `tmp_path`. Do not pass `NO_BUS` to `DelegateTo` or `WatchFile` in this task; that case is Task 2's, and until then it would write a spec file and then fail.

- [ ] **Step 7: Run the tests**

```bash
uv run python -m pytest tests/unit -v
```
Expected: PASS. A test that fails on a constructor arity is a call site you missed — fix the call, not the test.

- [ ] **Step 8: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `check_task.py`'s `run`, return `ctx.result(...)` instead of `ctx.failure(...)` for an unknown agent — the new no-bus test must fail on `checked.ok`.
2. In `worker.py`'s `available_tools`, pass `NO_BUS` to `CheckTask` instead of the `bus` parameter — a delegate or collect test in `tests/unit/test_tools.py` that expects a real task lookup must fail.

Restore both. If break 2 fails no test, say so in your report — it means the registry's bus wiring is unasserted, which is worth knowing.

- [ ] **Step 9: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 10: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Hand each tool the bus instead of a way to open one

Six tools built a LifecycleStore inside run from a run_dir, a clock and a
file system they were given for that purpose, so a tool's real
dependencies were invisible where it was constructed: check_task
declared three and used one.

The clock leaves five of them with nothing else to do.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: A tool that cannot queue, chosen at construction

**Files:**
- Create: `ancalagon/tools/delegate/delegating.py` — the shared name, description and args model
- Create: `ancalagon/tools/delegate/no_delegate_to.py`
- Create: `ancalagon/tools/watch/no_watch_file.py`
- Modify: `ancalagon/tools/delegate/delegate_to.py` — use the extracted builders
- Modify: `ancalagon/tools/delegate/delegate_tools.py` — choose per bus
- Modify: `ancalagon/worker.py:149` — choose per bus for `WatchFile`
- Test: `tests/unit/test_tools.py`, `tests/unit/test_watch.py`

**Interfaces:**
- Consumes: everything from Task 1, especially `delegate_tools(roles, caller, run_dir, parent, fs, bus)`.
- Produces:
  - `delegate_name(role_name: str) -> str`
  - `delegate_description(role_name: str, role: Role) -> str`
  - `delegate_args(role_name: str, role: Role) -> type[DelegateArgs]`
  - `NoDelegateTo(role_name: str, role: Role)`
  - `NoWatchFile(role: Role)`

**Why the extraction.** `DelegateTo.__init__` computes `self.name`, `self.description` and `self.args_model` (`delegate_to.py:32-48`), the last via `pydantic.create_model` embedding `resolve_class(role.input)`. `NoDelegateTo` must present a byte-identical schema or the model sees a different tool. Duplicating that is the verbatim-duplication defect; extracting it means both classes cannot drift.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_tools.py`:

```python
def test_a_delegate_tool_without_a_bus_keeps_its_schema_and_writes_nothing(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    role = Role(
        behaviour="Investigate.",
        tools=("submit_answer",),
        budget=finite_budget(3, 5),
    )
    real = DelegateTo(NO_BUS, "scout", role, ctx.workspace.write_root, 1, RealFileSystem())
    absent = NoDelegateTo("scout", role)

    assert absent.name == real.name
    assert absent.description == real.description
    assert absent.cost == real.cost
    assert absent.args_model.model_json_schema() == real.args_model.model_json_schema()

    refused = absent.run(
        DelegateArgs(task_id="analyse", goal="g", input=FreeText(text="i")), ctx
    )

    assert refused.ok is False
    assert refused.error == "cannot queue task analyse: this session has no bus"
    assert list((ctx.workspace.write_root / "tasks").glob("**/spec.json")) == []
```

The last assertion is the point of this task: nothing was written, so no orphan can exist. Construct `DelegateArgs` with whatever fields it really declares — read `delegate_args.py` — and if `args_model` requires a typed `input`, build the instance `absent.args_model` expects rather than a bare `DelegateArgs`.

Add to `tests/unit/test_watch.py` the same shape for `NoWatchFile`, asserting its `name` equals `WatchFile.name`, its error names the file it could not watch, and that `tmp_path` holds no `spec.json`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_tools.py tests/unit/test_watch.py -k no_bus -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.tools.delegate.no_delegate_to'`

- [ ] **Step 3: Extract the shared declaration**

Create `ancalagon/tools/delegate/delegating.py`:

```python
# What a delegate tool declares to the model, shared by the real one and the one with no bus.
import pydantic

from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.tools.delegate.delegate_args import DelegateArgs


def delegate_name(role_name: str) -> str:
    return f"delegate_{role_name}"


def delegate_description(role_name: str, role: Role) -> str:
    return (
        f"Queue a {role_name} task. Returns its task id immediately without waiting. "
        f"That agent is told: {role.behaviour} "
        "Reusing a task_id after that task has finished retries it, and the new agent "
        "inherits the previous one's transcript. Use a new task_id for a clean start."
    )


def delegate_args(role_name: str, role: Role) -> type[DelegateArgs]:
    return pydantic.create_model(
        f"DelegateTo{role_name.title().replace('_', '')}Args",
        __base__=DelegateArgs,
        input=(resolve_class(role.input), ...),
    )
```

Copy the description string from `delegate_to.py:33-38` verbatim — it is the text a model reads, and a reworded copy is a behaviour change. Check `delegate_args.py` for the real import path of `DelegateArgs`.

Then in `delegate_to.py`, replace those three computations with calls:

```python
        self.name = delegate_name(role_name)
        self.description = delegate_description(role_name, role)
        self.args_model = delegate_args(role_name, role)
```

- [ ] **Step 4: Write the two null tools**

`ancalagon/tools/delegate/no_delegate_to.py`:

```python
# The delegate tool a session gets when it has no bus: same schema, nothing queued, nothing written.
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.delegate.delegating import delegate_args, delegate_description, delegate_name
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class NoDelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(self, role_name: str, role: Role):
        self.name = delegate_name(role_name)
        self.description = delegate_description(role_name, role)
        self.args_model = delegate_args(role_name, role)

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        return ctx.failure(self.name, f"cannot queue task {args.task_id}: this session has no bus")
```

`ancalagon/tools/watch/no_watch_file.py`:

```python
# The watch tool a session gets when it has no bus: same schema, nothing queued, nothing written.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.watch.watch_args import WatchArgs
from ancalagon.tools.watch.watch_file import WatchFile


class NoWatchFile(Tool[WatchArgs]):
    name = WatchFile.name
    description = WatchFile.description
    cost = WatchFile.cost
    args_model = WatchFile.args_model

    def run(self, args: WatchArgs, ctx: ToolContext) -> ToolResult:
        return ctx.failure(self.name, f"cannot watch {args.path}: this session has no bus")
```

Referencing `WatchFile`'s class attributes is deliberate: it makes the two declarations provably identical rather than merely matching today. Check `watch_args.py` for the real field name — the failure message must interpolate a field that exists.

- [ ] **Step 5: Choose at construction**

`delegate_tools.py`:

```python
def _delegate(bus: Bus, name: str, role: Role, run_dir: pathlib.PurePath, parent: int, fs: FileSystem) -> Tool[DelegateArgs]:
    if bus is NO_BUS:
        return NoDelegateTo(name, role)
    return DelegateTo(bus, name, role, run_dir, parent, fs)


def delegate_tools(
    roles: collections.abc.Mapping[str, Role],
    caller: Role,
    run_dir: pathlib.PurePath,
    parent: int,
    fs: FileSystem,
    bus: Bus,
) -> list[BoundTool]:
    return [
        bound_for(_delegate(bus, name, role, run_dir, parent, fs), caller)
        for name, role in roles.items()
    ]
```

In `ancalagon/worker.py`, `build_registry`'s `WatchFile` construction at line 149 becomes the same choice. Extract a small helper beside it rather than inlining a conditional expression into the list comprehension — python-fp-lint caps complexity at 3.

This identity check is the only one in the change, it runs once per construction rather than per call, and it is what keeps every `run` body free of a branch. That trade is the spec's central decision; do not move the check into `run`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit/test_tools.py tests/unit/test_watch.py -v
```
Expected: PASS.

- [ ] **Step 7: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `no_delegate_to.py`, change the description to a different string — the schema-equality assertion must fail.
2. In `delegate_tools.py`'s `_delegate`, invert the condition so a real bus yields `NoDelegateTo` — an existing delegate test in `tests/unit/test_tools.py` must fail.

Restore both.

- [ ] **Step 8: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 9: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Choose a tool that cannot queue, rather than a branch inside one

delegate_to and watch_file wrote a task's spec.json before asking the bus
to queue it, so a session with no bus would leave a directory a later run
would read as a live task.

available_tools knows which bus it holds, so it picks the tool once. The
null pair carry the same name, description and schema, and hold no file
system at all: the orphan is impossible rather than cleaned up.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The answer path takes a bus too

**Files:**
- Modify: `ancalagon/answer.py:45-71` — `answer_task` takes a `Bus`, drops `run_dir` and `clock`
- Modify: `ancalagon/answer_command.py:11-16` — builds the `LifecycleStore` itself
- Modify: `ancalagon/tools/delegate/answer_task.py:29-41` — passes `self.bus`
- Test: `tests/unit/test_answer.py`

**Interfaces:**
- Consumes: `Bus` and `NO_BUS`; `AnswerTask(bus, parent, clock, fs)` from Task 1.
- Produces: `answer_task(bus, agent, answer, answered_by, clock, fs) -> AgentRef`

`clock` STAYS on `answer_task`. It is used at `answer.py:67` for the message timestamp (`ts=clock.now().isoformat()`), which has nothing to do with the bus. Only `run_dir` leaves.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_answer.py`:

```python
def test_answering_without_a_bus_refuses_before_writing_to_the_transcript(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    tool = AnswerTask(NO_BUS, parent=1, clock=FakeClock(), fs=RealFileSystem())

    refused = tool.run(AnswerArgs(task=7, answer="here"), ctx)

    assert refused.ok is False
    assert refused.error == "no agent 7"
```

This is the behaviour the spec predicted and measured: `_asked` raises `KeyError("no agent 7")` at `answer.py:25` on an empty snapshot, before the transcript write, and `AnswerTask.run` already catches `(KeyError, ValueError)`. Read `test_answer.py` for how it builds a `ToolContext` and whether it has a `_ctx` helper; reuse what is there.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_answer.py -k without_a_bus -v`
Expected: FAIL — `answer_task` still opens its own `LifecycleStore` from `run_dir`, so it reaches a real database or raises on a missing file rather than returning the refusal.

- [ ] **Step 3: Give `answer_task` a bus**

In `ancalagon/answer.py`, change the signature to take `bus: Bus` in place of `run_dir`, and delete the `bus = LifecycleStore.open(...)` line at 54. Keep `clock` and `fs` — both are still used, `clock` at line 67 and `fs` for the transcript. `task_dir` already comes from the snapshot (`task_of(snapshot, agent).dir`), so `run_dir` has no remaining use.

- [ ] **Step 4: Update the two callers**

`ancalagon/tools/delegate/answer_task.py` passes `self.bus` in place of `self.run_dir`.

`ancalagon/answer_command.py` builds the store it now has to supply:

```python
def answer_command(run_dir: pathlib.PurePath, agent: int, answer: str) -> int:
    fs = RealFileSystem()
    clock = SystemClock()
    bus = LifecycleStore.open(run_dir / "bus.db", clock, fs)
    resumed = answer_task(bus, agent, answer, answered_by=HUMAN, clock=clock, fs=fs)
    sys.stdout.write(f"answered agent {agent}; queued agent {resumed.id}\n")
    return 0
```

Do not change the message — `tests/unit/test_answer.py` asserts it exactly, and that assertion was added to catch an `AgentRef` leaking into it.

- [ ] **Step 5: Run the tests**

```bash
uv run python -m pytest tests/unit -v
```
Expected: PASS.

- [ ] **Step 6: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `answer.py`, move the `_answerable(snapshot, agent)` call to after the transcript write — the new no-bus test must still fail correctly, but a transcript file should now appear; assert its absence if the test does not already.
2. In `answer_command.py`, drop `.id` from the message — the exact-match assertion in `tests/unit/test_answer.py` must fail.

Restore both. Break 1 is the interesting one: it proves the ordering the spec relied on. If the test does not catch it, add the missing assertion rather than reporting the mutation as harmless.

- [ ] **Step 7: Full verification**

This is the final commit, so run everything:

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 8: Grep for anything left behind**

```bash
grep -rn "LifecycleStore.open\|LifecycleStore(" ancalagon --include="*.py" | grep -v pycache
```

After this task the only hits should be `ancalagon/run.py`, `ancalagon/worker.py`, `ancalagon/answer_command.py`, `ancalagon/note.py`, `ancalagon/trace_command.py` and `ancalagon/bus/lifecycle_store.py` itself. **No file under `ancalagon/tools/` should appear.** If one does, a tool still opens its own bus and the change is incomplete — report it.

- [ ] **Step 9: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Let the answer path be handed its bus as well

answer_task opened a database from a run_dir it was given for that
purpose alone, so the answer tool could reach one whatever it was
configured with. The CLI command now supplies the store, which is honest:
it already owns the clock and the file system.

No tool opens its own bus any more.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- The spec is `docs/superpowers/specs/2026-09-12-handing-a-tool-its-bus-design.md`. Read it before Task 1. It records why the null tools are chosen at construction rather than branched on inside `run`, and the three alternatives rejected — so you do not re-propose them.
- **Do not put a `bus is NO_BUS` check inside any `run` body.** The single identity check belongs in the construction helpers of Task 2. That is the spec's central decision.
- **Four tools need no null variant**: `check_task`, `collect_task`, `idle` and `answer_task` all degrade correctly on an empty snapshot, `answer_task` because `_asked` rejects an unknown agent before it writes. Do not add variants for them.
- Do not change any tool's behaviour under a real bus. Existing tests for that behaviour keep their assertions.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
