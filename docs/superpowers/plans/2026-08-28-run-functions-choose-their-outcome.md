# A Run Function Chooses Its Own Outcome — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic agent ends the way a session ends — its `run` function returns `Outcome[OutT]` and picks `Completed`, `Idling`, `NeedsInput` or `Failed` itself, which is what lets one spawn a child and be woken when that child settles.

**Architecture:** `contracts/outcome.py`'s concrete union becomes a generic type alias, which is the same type `outcome_adapter` builds at runtime, so that function is deleted. A new `outcome_arg` reader pulls the answer class out of `-> Outcome[X]` for contract derivation, `deterministic/run.py` writes what the function returned instead of wrapping it in `Completed`, and `RunContext` gains the agent id a run function needs to enqueue a child that can wake it.

**Tech Stack:** Python 3.13 (`type` statement generic aliases), Pydantic v2, pytest, uv, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-28-run-functions-choose-their-outcome-design.md`

## Global Constraints

Copied from `CLAUDE.md` and the project guidelines. Every task's requirements include these.

- Python 3.13+; every command runs under `uv run`.
- Pyright strict, zero errors. `Any` is banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` is banned as an annotation, except in the `collections.abc.Mapping[str, object]` hint signatures already present in `contracts/declared.py`.
- **No bare collection types, and no bare generics.** `Outcome` unparameterised is a Pyright `reportMissingTypeArgument` error; it is always `Outcome[SomeModel]` or `Outcome[pydantic.BaseModel]`.
- **No comments.** The only permitted comment is a one-line header at the top of a module stating its purpose. Every new file starts with one. No docstrings, no inline explanations, no section dividers, no TODOs.
- Dataclasses `frozen=True`; Pydantic models declared `frozen=True`. One class per file. Fully qualified imports, never relative. No static methods.
- Functional style: comprehensions over mutating loops, early return, small composable functions.
- No defensive programming, no workaround guards. The single top-level `try/except Exception` in `deterministic/run.py` is deliberate and stays.
- **Text is a boundary, never a carrier.** `model_validate_json` on arrival, `model_dump_json` at the file write, nothing in between.
- No `unittest.mock`. Concrete assertions — `assert result == 30`, never `assert x is not None`.
- **Assertions are sacred.** Do not remove or weaken an existing assertion.
- `README.md` and `docs/architecture.md` change in the same commit as the behaviour they describe.
- Verification before every commit: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`.
- A pre-commit hook also runs `python-fp-lint` (bans `list.insert()` and subscript mutation), Talisman, and a terminology guard. If `python-fp-lint` rejects code this plan gives literally, rewrite it in the codebase's own idiom (`match`/`case` is used for this elsewhere), keep behaviour identical, and say so in the report. If Talisman flags a false positive, append to `.talismanrc` with the checksum Talisman itself reports — never one from `shasum`.

---

## File Structure

**Task 1 — the alias**

| File | Responsibility |
|---|---|
| Modify `ancalagon/contracts/outcome.py` | `Outcome` becomes a generic alias; `outcome_adapter` deleted |
| Modify `ancalagon/tools/delegate/collect_task.py` | Builds its own `TypeAdapter` at the parse boundary |
| Modify `ancalagon/session.py` | Eight annotations gain their type argument |
| Modify `tests/unit/test_contracts.py`, `tests/unit/test_escalation.py` | Same assertions, against the alias |

**Task 2 — the run contract**

| File | Responsibility |
|---|---|
| Create `ancalagon/contracts/nothing.py` | The zero budget every deterministic outcome reports |
| Create `ancalagon/contracts/outcome_arg.py` | Reads the answer class out of `-> Outcome[X]` |
| Modify `ancalagon/contracts/run_contracts.py` | Uses `outcome_arg` for the return |
| Modify `ancalagon/deterministic/run.py` | `Run`'s return type; writes what it is handed |
| Modify `ancalagon/watch/watch_for.py` | Returns `Outcome[Watched]` with its own summary |
| Modify `tests/unit/test_config_load.py`, `tests/unit/test_deterministic.py` | Derivation and runner behaviour |
| Modify `README.md`, `docs/architecture.md` | The run-function rule |

**Task 3 — the agent id**

| File | Responsibility |
|---|---|
| Modify `ancalagon/deterministic/run_context.py` | Gains `agent_id: int` |
| Modify `ancalagon/deterministic/run.py` | Passes it |
| Modify `tests/unit/test_watch.py`, `tests/unit/test_deterministic.py` | Construction sites, and the assertion that it arrives |

---

### Task 1: The alias

No behaviour changes in this task. The same union, the same wire format, the same validation — said once, statically, instead of twice.

**Files:**
- Modify: `ancalagon/contracts/outcome.py`
- Modify: `ancalagon/tools/delegate/collect_task.py:17,88`
- Modify: `ancalagon/session.py:22` and its eight annotation sites
- Test: `tests/unit/test_contracts.py:15,78`, `tests/unit/test_escalation.py:17,54`

**Interfaces:**
- Produces: `ancalagon.contracts.outcome.Outcome`, a generic alias with one parameter bound to `pydantic.BaseModel`. Tasks 2 and 3 both depend on it.
- Removes: `ancalagon.contracts.outcome.outcome_adapter`.
- `SUMMARY_CHARS` stays exactly where it is.

- [ ] **Step 1: Write the failing test**

Replace the adapter block in `tests/unit/test_contracts.py` (currently lines 78–86, inside `test_contracts_round_trip_and_budget_arithmetic`) with one that names the type directly, and extend it to cover `Idling`, which the alias must carry and the current test never exercises:

```python
    adapter = pydantic.TypeAdapter(Outcome[NodeSummary])
    completed = Completed[NodeSummary](
        value=NodeSummary(text="done", confidence=2),
        summary="finished",
        spent=Budget(turns=1, tool_calls=2),
    )
    assert adapter.validate_json(completed.model_dump_json()) == completed
    failed = Failed(error="boom", summary="died", spent=Budget(turns=0, tool_calls=0))
    assert adapter.validate_json(failed.model_dump_json()) == failed
    idling = Idling(summary="waiting", spent=Budget(turns=0, tool_calls=0))
    assert adapter.validate_json(idling.model_dump_json()) == idling
    with pytest.raises(pydantic.ValidationError):
        adapter.validate_json(
            '{"kind":"completed","value":{"wrong":1},"summary":"s",'
            '"spent":{"turns":0,"tool_calls":0}}'
        )
```

Change the import at `tests/unit/test_contracts.py:15` from `from ancalagon.contracts.outcome import outcome_adapter` to `from ancalagon.contracts.outcome import Outcome`, and add `from ancalagon.contracts.idling import Idling`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest tests/unit/test_contracts.py -v`
Expected: FAIL. `Outcome` is a concrete union today, so `Outcome[NodeSummary]` raises `TypeError: ... is not subscriptable`.

- [ ] **Step 3: Make `Outcome` generic**

`ancalagon/contracts/outcome.py` in full:

```python
# The ways an attempt can end, whatever produced it.
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.needs_input import NeedsInput

SUMMARY_CHARS = 200

type Outcome[OutT: pydantic.BaseModel] = (
    Completed[OutT] | Exhausted[OutT] | NeedsInput | Failed | Idling
)
```

`outcome_adapter` is gone, and with it the `Completed[pydantic.BaseModel] | ...` concrete union.

- [ ] **Step 4: Update the one caller**

In `ancalagon/tools/delegate/collect_task.py`, change the import at line 17 from `from ancalagon.contracts.outcome import Outcome, outcome_adapter` to `from ancalagon.contracts.outcome import Outcome`, add `import pydantic` if the file does not already have it, and change the parse at line 88:

```python
        outcome = pydantic.TypeAdapter(Outcome[answer_class]).validate_json(
            self.fs.read_text(task_dir / f"outcome-{newest}.json")
        )
```

`_detail`'s parameter at line 30 becomes `outcome: Outcome[pydantic.BaseModel]`.

- [ ] **Step 5: Parameterise the annotations in `session.py`**

Eight sites. `ancalagon/session.py` already imports `pydantic` at line 5, so no new import is needed:

| Line | Was | Becomes |
|---|---|---|
| 218 | `-> Outcome \| Pending:` | `-> Outcome[pydantic.BaseModel] \| Pending:` |
| 243 | `-> Outcome \| Pending:` | `-> Outcome[pydantic.BaseModel] \| Pending:` |
| 250 | `-> Outcome \| Pending:` | `-> Outcome[pydantic.BaseModel] \| Pending:` |
| 261 | `-> Outcome \| Pending:` | `-> Outcome[pydantic.BaseModel] \| Pending:` |
| 282 | `-> Outcome \| Pending:` | `-> Outcome[pydantic.BaseModel] \| Pending:` |
| 299 | `-> Outcome:` | `-> Outcome[pydantic.BaseModel]:` |
| 306 | `-> Outcome:` | `-> Outcome[pydantic.BaseModel]:` |
| 313 | `-> Outcome:` | `-> Outcome[pydantic.BaseModel]:` |

Line numbers drift as you edit; the reliable move is `grep -n 'Outcome' ancalagon/session.py` and parameterise every hit except the import on line 22. Do not change the import — it still reads `from ancalagon.contracts.outcome import SUMMARY_CHARS, Outcome`.

Then `tests/unit/test_escalation.py:54`, `_run`'s return annotation, becomes `-> Outcome[pydantic.BaseModel]:`, and the file needs `import pydantic` if it does not have it.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
```

Expected: PASS. If any test other than `test_contracts.py` and `test_escalation.py` needed changing, stop and report it — this task is not supposed to change behaviour, so a test that moves is evidence something did.

- [ ] **Step 7: Mutation-check the new assertion**

Temporarily change the alias to `Completed[pydantic.BaseModel] | Exhausted[OutT] | NeedsInput | Failed | Idling` and confirm the wrong-`value` assertion in `test_contracts.py` fails, because the erased member now accepts anything. Restore it.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add ancalagon/contracts/outcome.py ancalagon/tools/delegate/collect_task.py ancalagon/session.py tests/unit
git commit -m "Outcome is one generic alias, not a union written twice"
```

---

### Task 2: The run contract

**Files:**
- Create: `ancalagon/contracts/nothing.py`, `ancalagon/contracts/outcome_arg.py`
- Modify: `ancalagon/contracts/run_contracts.py`, `ancalagon/deterministic/run.py`, `ancalagon/watch/watch_for.py`
- Modify: `README.md`, `docs/architecture.md`
- Test: `tests/unit/test_config_load.py`, `tests/unit/test_deterministic.py`

**Interfaces:**
- Consumes: `Outcome` as a generic alias (Task 1).
- Produces: `ancalagon.contracts.nothing.NOTHING: Budget` — `Budget(turns=0, tool_calls=0)`.
- Produces: `ancalagon.contracts.outcome_arg.outcome_arg(found: collections.abc.Callable[..., object]) -> Declared`, returning the same `(type | None, str)` pair `ancalagon.contracts.declared.declared` returns.
- Produces: `run_contracts(ref)` unchanged in signature — still `-> tuple[ClassRef, ClassRef]` — but now requiring the return annotation to be `Outcome[X]`.
- Produces: `ancalagon.deterministic.run.Run.__call__` returning `Outcome[pydantic.BaseModel]`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_config_load.py`, the `RUNNERS` module string is what derivation is tested against. Every function that should still load gets the new return shape, and three refusal cases are added. Replace `RUNNERS` with:

```python
RUNNERS = '''
import pydantic

from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.outcome import Outcome


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    at: float


def good(given: Given, ctx: pydantic.BaseModel) -> Outcome[Produced]:
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)


def one_parameter(given: Given) -> Outcome[Produced]:
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)


def bare(given, ctx) -> Outcome[Produced]:
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)


def not_a_model(given: int, ctx: pydantic.BaseModel) -> Outcome[Produced]:
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)


def no_return(given: Given, ctx: pydantic.BaseModel):
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)


def returns_a_scalar(given: Given, ctx: pydantic.BaseModel) -> int:
    return 1


def returns_a_bare_model(given: Given, ctx: pydantic.BaseModel) -> Produced:
    return Produced(at=1.0)


def returns_an_unparameterised_outcome(given: Given, ctx: pydantic.BaseModel) -> Outcome:
    return Completed(value=Produced(at=1.0), summary="done", spent=NOTHING)
'''
```

`returns_an_unparameterised_outcome` would be a Pyright error if written in a real module; `RUNNERS` is a string written to a temp file, so nothing type-checks it, and that is exactly the case the runtime check must catch.

Then extend the derivation test. The existing assertions for `one_parameter`, `bare`, `not_a_model` and `no_return` stay exactly as they are — the arity and first-parameter rules did not change. Add three:

```python
    assert fault("returns_a_scalar") == (
        "returns_a_scalar in runkit.runners annotates return as <class 'int'>, "
        "which is not Outcome[...]"
    )
    assert "which is not Outcome[...]" in fault("returns_a_bare_model")
    assert "which is not one model class" in fault("returns_an_unparameterised_outcome")
```

and confirm the happy path still derives `answer=Produced` from `Outcome[Produced]` rather than from a bare annotation — the existing assertion `role.answer == ClassRef(module="runkit.runners", name="Produced")` already says this and must keep passing unchanged.

In `tests/unit/test_deterministic.py`, `RUNNERS` gains the new shape and one new function, and a new test asserts the runner writes an `Idling` the function chose:

```python
RUNNERS = """
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.deterministic.run_context import RunContext


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    seen: str


def echo(given: Given, ctx: RunContext) -> Outcome[Produced]:
    seen = ctx.fs.read_text(ctx.task_dir / given.path)
    return Completed(value=Produced(seen=seen), summary=f"read {given.path}", spent=NOTHING)


def waits(given: Given, ctx: RunContext) -> Outcome[Produced]:
    return Idling(summary="waiting for a child", spent=NOTHING)


def explodes(given: Given, ctx: RunContext) -> Outcome[Produced]:
    raise RuntimeError("the transform gave up")
"""
```

The existing completed test's summary assertion changes, because the summary is now the function's sentence rather than a truncated dump:

```python
    assert written["summary"] == "read board.md"
```

Its `written["value"] == {"seen": "a claim appeared"}`, `written["spent"]`, and directory-contents assertions are unchanged. Add:

```python
def test_a_run_function_may_idle_instead_of_completing(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "waits")

    assert main(tmp_path, task_dir, 7, config_path) == 0

    written = json.loads((task_dir / "outcome-7.json").read_text())
    assert written["kind"] == "idling"
    assert written["summary"] == "waiting for a child"
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert "value" not in written
```

`main` returns 0 for an idling outcome: the process did its job. Only an escaped exception returns 1.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/unit/test_config_load.py tests/unit/test_deterministic.py -v
```

Expected: FAIL. `ModuleNotFoundError: No module named 'ancalagon.contracts.nothing'` from the fixture modules, and once that exists, `run_contracts` refusing `Outcome[Produced]` with "annotates return as ... which is not a model class" — the old rule rejecting the new shape.

- [ ] **Step 3: The shared zero budget**

```python
# ancalagon/contracts/nothing.py
# The budget a deterministic outcome reports: an agent with no model spends nothing.
from ancalagon.contracts.budget import Budget

NOTHING = Budget(turns=0, tool_calls=0)
```

In `ancalagon/deterministic/run.py`, delete the module-level `NOTHING = Budget(turns=0, tool_calls=0)` at line 26 and the now-unused `from ancalagon.contracts.budget import Budget` import, replacing them with `from ancalagon.contracts.nothing import NOTHING`.

- [ ] **Step 4: The return reader**

```python
# ancalagon/contracts/outcome_arg.py
# The answer class a run function names by returning Outcome[X], and what to say otherwise.
import collections.abc
import typing

import pydantic

from ancalagon.contracts.declared import Declared
from ancalagon.contracts.outcome import Outcome


def outcome_arg(found: collections.abc.Callable[..., object]) -> Declared:
    try:
        hints = typing.get_type_hints(found)
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"
    if "return" not in hints:
        return None, "does not annotate its return"
    ret = hints["return"]
    if typing.get_origin(ret) is not Outcome:
        return None, f"annotates return as {ret}, which is not Outcome[...]"
    match typing.get_args(ret):
        case (arg,) if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
            return arg, ""
        case args:
            return None, f"parameterises Outcome with {args}, which is not one model class"
```

`typing.get_origin` on `Outcome[Watched]` returns the alias object `Outcome` itself, and `typing.get_args` returns `(Watched,)` — both confirmed against the real interpreter before this design was chosen, not assumed.

- [ ] **Step 5: Derive the answer from it**

In `ancalagon/contracts/run_contracts.py`, add `from ancalagon.contracts.outcome_arg import outcome_arg` and split the two readers, since `_must` currently calls `annotation_fault` for both:

```python
def _must(pair: Declared, ref: FunctionRef) -> type[pydantic.BaseModel]:
    match pair:
        case (None, fault):
            raise ValueError(f"{ref.name} in {ref.module} {fault}")
        case (declared, _):
            return declared


def run_contracts(ref: FunctionRef) -> tuple[ClassRef, ClassRef]:
    found = _found(ref)
    if fault := arity_fault(found, RUN_ARITY):
        raise ValueError(f"{ref.name} in {ref.module} {fault}")
    first = next(iter(inspect.signature(found).parameters.values())).name
    given = _must(annotation_fault(found, first, f"its first parameter, {first}"), ref)
    produced = _must(outcome_arg(found), ref)
    return _ref_of(given), _ref_of(produced)
```

`_must` now takes the pair rather than producing it, so both readers feed the same error path and the message prefix stays `f"{ref.name} in {ref.module} "` for every fault. Add `from ancalagon.contracts.declared import Declared, annotation_fault` and drop the now-unused `key`/`label` parameters.

- [ ] **Step 6: Stop wrapping in the runner**

In `ancalagon/deterministic/run.py`, the protocol's return type changes and `_completed` becomes `_outcome`:

```python
@typing.runtime_checkable
class Run(typing.Protocol):
    def __call__(
        self, given: pydantic.BaseModel, ctx: RunContext
    ) -> Outcome[pydantic.BaseModel]: ...


def _outcome(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    config_path: pathlib.PurePath,
    fs: FileSystem,
) -> Outcome[pydantic.BaseModel]:
    load_config(config_path, fs)
    spec_text = fs.read_text(task_dir / "spec.json")
    spec = TaskSpec.model_validate_json(spec_text)
    input_class = resolve_class(spec.role.input)
    given = AgentSpec[input_class].model_validate_json(spec_text).input
    ctx = RunContext(fs=fs, clock=SystemClock(), task_dir=task_dir, run_dir=run_dir)
    return resolve_run(spec.role.run)(given, ctx)
```

and `main`'s try block writes what it was handed:

```python
    try:
        produced = _outcome(run_dir, task_dir, config_path, fs)
        fs.write_text(outcome_path, produced.model_dump_json())
        return 0
    except Exception as exc:
        failure = Failed(
            error=traceback.format_exc(), summary=str(exc)[:SUMMARY_CHARS], spent=NOTHING
        )
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1
```

Add `from ancalagon.contracts.outcome import SUMMARY_CHARS, Outcome`, and drop the `Completed` import — the runner no longer constructs one.

- [ ] **Step 7: Rewrite the one run function there is**

```python
# ancalagon/watch/watch_for.py
# Waits for a file to change, then ends. The whole of a watcher.
import pathlib

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched
from ancalagon.deterministic.run_context import RunContext

WATCH_FOR = FunctionRef(module="ancalagon.watch.watch_for", name="watch_for")


def watch_for(request: WatchRequest, ctx: RunContext) -> Outcome[Watched]:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    at = ctx.fs.changed_at(watched)
    return Completed(
        value=Watched(path=request.path, at=at),
        summary=f"{request.path} changed at {at}",
        spent=NOTHING,
    )
```

`tests/unit/test_watch.py`'s `test_a_watcher_waits_until_the_file_it_was_given_changes` calls `watch_for` directly and asserts on `watched.path` and `watched.at`. It now receives a `Completed`, so those become `outcome.value.path` and `outcome.value.at`, and add an assertion on the sentence that came back:

```python
    outcome = watch_for(WatchRequest(path=str(board), since=before), ctx)

    assert clock.slept == 3
    assert isinstance(outcome, Completed)
    assert outcome.value.path == str(board)
    assert outcome.value.at > before
    assert outcome.summary == f"{board} changed at {outcome.value.at}"
    assert outcome.spent == Budget(turns=0, tool_calls=0)
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
uv run python -m pytest tests/integration/test_blackboard.py -v
```

Expected: PASS both. The blackboard test is the end-to-end proof that a real supervisor, a real subprocess and a real run function still agree.

- [ ] **Step 9: Mutation-check**

Break the two things this task claims, and confirm the right test fails each time:

- In `outcome_arg`, change `if typing.get_origin(ret) is not Outcome:` to `if False:` — `returns_a_bare_model` and `returns_a_scalar` must stop being refused.
- In `main`, wrap the returned outcome back up as `Completed(value=produced, summary="", spent=NOTHING)` — `test_a_run_function_may_idle_instead_of_completing` must fail on `written["kind"]`.

Restore both.

- [ ] **Step 10: Update the living docs**

`README.md`'s run-function rule currently reads:

> A run function takes two positional parameters — the first annotated with the input contract, the second `RunContext` — and returns the answer contract by its return annotation.

It becomes a statement that the function returns `Outcome[X]`, that `X` is the answer contract, and that the function chooses its own ending — `Completed` when it has an answer, `Idling` when it has spawned a child and wants to be woken, `NeedsInput` to ask its parent, `Failed` to report a failure it handled. Say that a deterministic agent reports `spent=NOTHING`. Update the example so it returns an `Outcome`.

`docs/architecture.md`'s deterministic-child section says the runner "calls the named function with that input and a `RunContext`, and writes" the outcome. Correct it to say the runner writes whatever outcome the function returned, and that the function picks the same ending a session picks — which is what makes the two indistinguishable to a parent.

- [ ] **Step 11: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
uv run python -m pytest tests/integration/test_blackboard.py
git add ancalagon tests README.md docs/architecture.md
git commit -m "A run function returns its outcome, and picks which one"
```

---

### Task 3: The agent id

**Files:**
- Modify: `ancalagon/deterministic/run_context.py`, `ancalagon/deterministic/run.py`
- Test: `tests/unit/test_deterministic.py`, `tests/unit/test_watch.py`

**Interfaces:**
- Consumes: `Outcome[OutT]` as a run function's return type (Task 2).
- Produces: `RunContext(fs, clock, task_dir, run_dir, agent_id)` — five fields, `agent_id: int` last.

- [ ] **Step 1: Write the failing test**

Add a run function to `tests/unit/test_deterministic.py`'s `RUNNERS` that reports what it was given, so the assertion is on a value rather than on a field's existence:

```python
def reports_its_agent(given: Given, ctx: RunContext) -> Outcome[Produced]:
    return Completed(
        value=Produced(seen=str(ctx.agent_id)), summary=f"agent {ctx.agent_id}", spent=NOTHING
    )
```

and the test:

```python
def test_a_run_function_is_told_which_agent_it_is(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "reports_its_agent")

    assert main(tmp_path, task_dir, 12, config_path) == 0

    written = json.loads((task_dir / "outcome-12.json").read_text())
    assert written["value"] == {"seen": "12"}
    assert written["summary"] == "agent 12"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run python -m pytest tests/unit/test_deterministic.py::test_a_run_function_is_told_which_agent_it_is -v`
Expected: FAIL. The outcome is `failed`, because `RunContext` has no `agent_id` and the run function raises `AttributeError`, which `main`'s `except` turns into a `Failed` outcome and a return of 1 — so the `main(...) == 0` assertion is what fails first.

- [ ] **Step 3: Add the field**

```python
# ancalagon/deterministic/run_context.py
# What a run function is given besides its input: the ports, where this task lives,
# and which agent it is.
import dataclasses
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.fs.file_system import FileSystem


@dataclasses.dataclass(frozen=True)
class RunContext:
    fs: FileSystem
    clock: Clock
    task_dir: pathlib.PurePath
    run_dir: pathlib.PurePath
    agent_id: int
```

- [ ] **Step 4: Thread it through the runner**

`_outcome` gains the parameter and passes it; `main` supplies the value it already has:

```python
def _outcome(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
    fs: FileSystem,
) -> Outcome[pydantic.BaseModel]:
    load_config(config_path, fs)
    spec_text = fs.read_text(task_dir / "spec.json")
    spec = TaskSpec.model_validate_json(spec_text)
    input_class = resolve_class(spec.role.input)
    given = AgentSpec[input_class].model_validate_json(spec_text).input
    ctx = RunContext(
        fs=fs,
        clock=SystemClock(),
        task_dir=task_dir,
        run_dir=run_dir,
        agent_id=agent_id,
    )
    return resolve_run(spec.role.run)(given, ctx)
```

and its call in `main` becomes `_outcome(run_dir, task_dir, agent_id, config_path, fs)`.

- [ ] **Step 5: Update the other construction site**

`tests/unit/test_watch.py` builds a `RunContext` directly in `test_a_watcher_waits_until_the_file_it_was_given_changes`. Add `agent_id=1` to it. `grep -rn 'RunContext(' ancalagon tests` to confirm there are no others.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
```

Expected: PASS.

- [ ] **Step 7: Mutation-check**

Change `agent_id=agent_id` in `_outcome` to `agent_id=0` and confirm `test_a_run_function_is_told_which_agent_it_is` fails on `written["value"]`. Restore it.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
uv run python -m pytest tests/integration/test_blackboard.py
git add ancalagon tests
git commit -m "A run function is told which agent it is"
```

---

## Self-Review

**Spec coverage.** Every section maps to a task: the alias, the deletion of `outcome_adapter`, and the parameterised annotations to Task 1; `outcome_arg`, the derivation rule, the runner no longer wrapping, `watch_for`'s rewrite and the docs to Task 2; `RunContext.agent_id` to Task 3. The spec's "What this does not do" section — no spawning helper, no check that an `Idling` is honest — correctly has no task, because both are things the change deliberately omits.

One addition the spec implies but does not name: `NOTHING` moves from `deterministic/run.py` into `ancalagon/contracts/nothing.py`, because `watch_for` now needs it too and `ancalagon.watch` importing `ancalagon.deterministic.run` would pull `argparse` and the config loader into a leaf function's import graph.

One clarification the spec leaves open and this plan settles: `main` returns 0 for an idling outcome. Only an escaped exception returns 1. The supervisor reads the outcome file for the kind, so the exit code says whether the process did its job, not whether the agent finished its work.

**Types.** `Outcome` takes one parameter bound to `pydantic.BaseModel` in Task 1 and is subscripted that way in Tasks 2 and 3; `outcome_arg` returns `Declared`, the same pair `declared` returns, so `run_contracts._must` consumes either; `RunContext`'s five field names are identical across `run.py`, `watch_for.py`, `test_watch.py` and both fixture modules; `NOTHING` is imported from `ancalagon.contracts.nothing` everywhere after Task 2.
