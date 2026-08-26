# Deterministic Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A role may name a Python function instead of describing behaviour to a model; the harness derives its input and answer contracts from the function's signature, runs it in a process, and the parent that delegated to it cannot tell the difference.

**Architecture:** `ClassRef` and `FunctionRef` stop holding file paths and hold dotted module names, so a class introspected out of a signature converts back to a ref with `cls.__module__`. `Role` gains `run: FunctionRef`; `config/load.py` fills `input` and `answer` from the run function's signature at load, so `Role` and every consumer of it are unchanged past that point. A generic runner reads `spec.json`, calls the function with a `RunContext`, and writes `outcome-<agent>.json` — the contract `ancalagon/watch/watch.py` already honours by hand. `watch.py`, `WatchSpawner` and `SpawnByInput` are deleted at the end, replaced by the general case.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, uv, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-27-deterministic-agents-design.md`

## Global Constraints

Copied from `CLAUDE.md` and the project guidelines. Every task's requirements include these.

- Python 3.13+; every command runs under `uv run`.
- Pyright strict, zero errors. `Any` is banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and JSON-blob aliases are equally banned.
- Every generic is parameterised: `dict[str, int]`, `tuple[type[pydantic.BaseModel], ...]`, never bare `dict`/`tuple`.
- No comments. The only permitted comment is a one-line header at the top of a module stating its purpose. Every new file in this plan starts with one.
- Dataclasses are `frozen=True`. Pydantic models are declared `frozen=True`.
- One class per file. Fully qualified imports, never relative.
- No `None` defaults, no `None` returns from non-`None` signatures; use a null-object constant (`FREE_TEXT` is the existing example, `NO_RUN` is the one this plan adds).
- No `unittest.mock`. Fakes and fixtures only.
- Few tests, each covering a whole behaviour — one test per coherent behaviour, asserting everything that behaviour implies.
- Concrete assertions. `assert result == 30`, never `assert result is not None`.
- Verification before each commit: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`.
- Never name an external codebase under analysis in a tracked artifact.

---

## File Structure

**Task 1 — dotted refs**

| File | Responsibility |
|---|---|
| Create `ancalagon/contracts/dotted.py` | The one regex a dotted module name must match |
| Modify `ancalagon/contracts/class_ref.py` | `module` gains the dotted pattern |
| Modify `ancalagon/contracts/function_ref.py` | Same pattern on both fields |
| Modify `ancalagon/contracts/resolve.py` | `importlib.import_module`; `module_of` and `_load_fresh` deleted |
| Modify `ancalagon/contracts/role.py` | `FREE_TEXT` names a dotted module |
| Create `ancalagon/config/importable.py` | Puts a config's own directory on `sys.path` |
| Modify `ancalagon/config/load.py` | Calls `importable`; `_class_ref`/`_hooks` stop rooting paths |
| Modify `ancalagon/tools/registry/accepts.py` | Imports the module by dotted name |
| Modify `ancalagon/tools/registry/resolve_before.py`, `resolve_after.py` | Same |
| Create `tests/unit/conftest.py` fixture `importable` | Adds a directory to `sys.path` and undoes it, including modules it caused |
| Modify `tests/unit/test_contracts.py`, `test_config_load.py`, `test_hooks.py`, `test_cli_settings.py`, `test_watch.py` | Dotted refs and packages instead of loose files |

**Task 2 — `Role.run` and derivation**

| File | Responsibility |
|---|---|
| Create `ancalagon/contracts/declared.py` | The shared "this annotation is a model class" check |
| Modify `ancalagon/tools/registry/accepts.py` | Uses `declared` instead of its private copy |
| Create `ancalagon/contracts/no_run.py` | The function `NO_RUN` names; a role served by a model |
| Modify `ancalagon/contracts/role.py` | `run: FunctionRef = NO_RUN` |
| Create `ancalagon/contracts/run_contracts.py` | Signature → `(input ClassRef, answer ClassRef)` |
| Modify `ancalagon/config/raw_role.py` | `run: RawClassRef = RawClassRef()` |
| Modify `ancalagon/config/load.py` | `_role` derives the contracts, refuses a role that declares both |
| Modify `tests/unit/test_config_load.py` | Derivation and its refusals |

**Task 3 — the runner**

| File | Responsibility |
|---|---|
| Create `ancalagon/deterministic/__init__.py` | Package marker |
| Create `ancalagon/deterministic/run_context.py` | `RunContext` frozen dataclass |
| Create `ancalagon/deterministic/run.py` | `Run` protocol, `resolve_run`, `main`, `cli` |
| Modify `ancalagon/supervisor/subprocess_spawner.py` | Takes the module it runs |
| Modify `ancalagon/cli.py`, `tests/unit/test_sandbox.py`, `tests/integration/test_blackboard.py` | Pass the module |
| Modify `pyproject.toml` | `ancalagon.deterministic` joins the two forbidden-import contracts |
| Create `tests/unit/test_deterministic.py` | The runner's two behaviours |

**Task 4 — collapse `watch`**

| File | Responsibility |
|---|---|
| Create `ancalagon/watch/watch_for.py` | `watch_for` alone, with the `RunContext` signature |
| Delete `ancalagon/watch/watch.py`, `ancalagon/supervisor/watch_spawner.py`, `ancalagon/supervisor/spawn_by_input.py` | Replaced by the general case |
| Create `ancalagon/supervisor/spawn_by_run.py` | Routes on whether the role declares a run function |
| Modify `ancalagon/cli.py` | `_spawner` rewritten |
| Modify `tests/unit/test_watch.py`, `tests/integration/test_blackboard.py` | Wiring only |
| Modify `README.md`, `docs/architecture.md` | Living docs |

---

### Task 1: Dotted refs

**Files:**
- Create: `ancalagon/contracts/dotted.py`
- Create: `ancalagon/config/importable.py`
- Modify: `ancalagon/contracts/class_ref.py`, `ancalagon/contracts/function_ref.py`, `ancalagon/contracts/resolve.py`, `ancalagon/contracts/role.py`
- Modify: `ancalagon/config/load.py`
- Modify: `ancalagon/tools/registry/accepts.py`, `ancalagon/tools/registry/resolve_before.py`, `ancalagon/tools/registry/resolve_after.py`
- Test: `tests/unit/conftest.py`, `tests/unit/test_contracts.py`, `tests/unit/test_config_load.py`, `tests/unit/test_hooks.py`, `tests/unit/test_cli_settings.py`, `tests/unit/test_watch.py`

**Interfaces:**
- Produces: `ancalagon.contracts.dotted.DOTTED: str` — the regex.
- Produces: `ancalagon.config.importable.importable(base: pathlib.PurePath) -> None`.
- Produces: `resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]`, signature unchanged, now resolving `ref.module` as a dotted name.
- Produces: `tests/unit/conftest.py` fixture `importable` of type `collections.abc.Callable[[pathlib.Path], None]`.
- Removes: `ancalagon.contracts.resolve.module_of` and `_load_fresh`.

- [ ] **Step 1: Write the failing tests**

Replace the resolution parts of `tests/unit/test_contracts.py`. In `test_contracts_round_trip_and_budget_arithmetic`, the three `ClassRef(module="node_summary.py", ...)` occurrences at lines 40, 41 and 56 become `ClassRef(module="node_summary", name="NodeSummary")`, and the `verdict.py` block at the end of that test (lines 87–92) is deleted — resolution now lives entirely in the role test below.

Replace `test_a_role_defaults_to_prose_and_resolves_the_contracts_it_names` wholesale. Its old point — two files both called `shapes.py` in different directories resolving to different classes — is exactly what dotted names give up, so the behaviour under test changes:

```python
def test_a_role_defaults_to_prose_and_resolves_the_contracts_it_names(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(
        "import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n"
    )
    importable(tmp_path)

    prose = Role(
        behaviour="Investigate.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8)
    )
    assert resolve_class(prose.input) is FreeText
    assert resolve_class(prose.answer) is FreeText

    named = Role(
        behaviour="Analyse.",
        answer=ClassRef(module="shapekit.shapes", name="Component"),
        tools=("read_file",),
        budget=Budget(turns=4, tool_calls=8),
    )
    component = resolve_class(named.answer)
    assert component.model_fields.keys() == {"name"}
    assert resolve_class(named.answer) is component
    assert resolve_class(named.input) is FreeText

    with pytest.raises(pydantic.ValidationError):
        ClassRef(module="shapekit.shapes", name="not a class")
    with pytest.raises(pydantic.ValidationError):
        ClassRef(module="./shapekit/shapes.py", name="Component")
    with pytest.raises(pydantic.ValidationError):
        ClassRef(module=str(tmp_path / "shapekit" / "shapes.py"), name="Component")

    with pytest.raises(AttributeError):
        resolve_class(ClassRef(module="shapekit.shapes", name="Absent"))
    with pytest.raises(ModuleNotFoundError):
        resolve_class(ClassRef(module="shapekit.absent", name="Component"))
```

Add the fixture to `tests/unit/conftest.py`, appended below `settle`:

```python
import collections.abc
import pathlib
import sys

import pytest


@pytest.fixture
def importable() -> collections.abc.Iterator[collections.abc.Callable[[pathlib.Path], None]]:
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    yield lambda directory: sys.path.insert(0, str(directory))
    sys.path[:] = path_before
    for name in set(sys.modules) - modules_before:
        del sys.modules[name]
```

In `tests/unit/test_config_load.py`, rewrite `test_roles_load_with_their_contracts_and_prose_is_the_absent_default` so the contract lives in a package beside the config, which is what proves `load_config` made that directory importable:

```python
def test_roles_load_with_their_contracts_and_prose_is_the_absent_default(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(
        "import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n"
    )
    importable(tmp_path)
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "shapekit.shapes", name = "Component" }
tools = ["read_file", "delegate_scout"]
budget = { turns = 12, tool_calls = 30 }

[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
""",
    )

    roles = load_config(config, RealFileSystem()).roles

    assert sorted(roles) == ["analyst", "scout"]
    assert roles["analyst"].behaviour == "Analyse."
    assert roles["analyst"].answer == ClassRef(module="shapekit.shapes", name="Component")
    assert roles["analyst"].tools == ("read_file", "delegate_scout")
    assert roles["analyst"].budget == Budget(turns=12, tool_calls=30)
    assert roles["scout"].answer == FREE_TEXT
    assert roles["scout"].input == FREE_TEXT
```

The `importable` fixture is requested here purely to undo what `load_config` does to `sys.path`; the assertion that resolution works is the `resolve_class` call the loader itself makes when Task 2 lands, and until then the ref equality is the whole claim.

Add a new test to the same file for the refusal:

```python
def test_a_config_naming_a_file_path_is_refused_at_load(tmp_path: pathlib.Path):
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "./shapes.py", name = "Component" }
tools = ["read_file"]
budget = { turns = 12, tool_calls = 30 }
""",
    )

    with pytest.raises(pydantic.ValidationError, match="module"):
        load_config(config, RealFileSystem())
```

In `tests/unit/test_hooks.py`, the `hooks` fixture writes a package instead of a loose module and returns the dotted name:

```python
@pytest.fixture
def hooks(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
) -> str:
    package = tmp_path / "hookkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "hooks.py").write_text(MODULE)
    importable(tmp_path)
    return "hookkit.hooks"
```

Every `FunctionRef(module=str(hooks), ...)` in that file becomes `FunctionRef(module=hooks, ...)`, and the type of the `hooks` parameter on each test changes from `pathlib.Path` to `str`. The `CONFIG` block's three `{ module = "./hooks.py", ... }` entries become `{ module = "hookkit.hooks", ... }`, and the test that loads it writes the same package into `tmp_path` first. All eight message assertions in `test_a_hook_is_accepted_only_when_it_can_receive_what_the_tool_will_pass` stay exactly as they are — the wording does not change in this task.

In `tests/unit/test_cli_settings.py`, `test_the_root_spec_comes_from_its_role_and_its_two_files` writes `querykit/shapes.py` into `tmp_path` with the `Query` model, requests the `importable` fixture, calls it with `tmp_path`, and uses `ClassRef(module="querykit.shapes", name="Query")`.

In `tests/unit/test_watch.py`, delete the `WATCHES` constant and use `WatchRequest.__module__` at its one use site (line 226) — the same value, now correct by construction rather than by a path rebuilt from a dotted name.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/unit/test_contracts.py tests/unit/test_config_load.py tests/unit/test_hooks.py -v
```

Expected: FAIL. `test_a_config_naming_a_file_path_is_refused_at_load` fails because no pattern rejects it yet; the `ClassRef(module="./shapekit/shapes.py", ...)` assertions fail for the same reason; `resolve_class(ClassRef(module="shapekit.shapes", ...))` fails with `FileNotFoundError` or `ImportError` because `resolve` still treats the module as a path.

- [ ] **Step 3: Add the pattern**

```python
# ancalagon/contracts/dotted.py
# The shape of a dotted module name, shared by every ref that names one.
DOTTED = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"
IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"
```

```python
# ancalagon/contracts/class_ref.py
# Names one contract class by the dotted module that defines it.
import pydantic

from ancalagon.contracts.dotted import DOTTED, IDENTIFIER


class ClassRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=DOTTED)
    name: str = pydantic.Field(pattern=IDENTIFIER)
```

```python
# ancalagon/contracts/function_ref.py
# Where a function lives: the dotted module a role named, and the name inside it.
import pydantic

from ancalagon.contracts.dotted import DOTTED, IDENTIFIER


class FunctionRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=DOTTED)
    name: str = pydantic.Field(pattern=IDENTIFIER)
```

- [ ] **Step 4: Resolve by import**

```python
# ancalagon/contracts/resolve.py
# Imports a contract module by the dotted name its ClassRef gives.
import importlib

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]:
    resolved = getattr(importlib.import_module(ref.module), ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
```

`module_of`, `_load_fresh`, and the `functools`, `importlib.util`, `pathlib`, `sys` and `types` imports all go. `sys.modules` is already the cache `functools.cache` was standing in for.

In `ancalagon/contracts/role.py`, `FREE_TEXT` stops going through `__file__`:

```python
FREE_TEXT = ClassRef(module="ancalagon.contracts.free_text", name="FreeText")
```

The `import ancalagon.contracts.free_text` and `import pathlib` lines at the top of `role.py` are then unused and go with it.

Update the three call sites that used `module_of`. In `ancalagon/tools/registry/accepts.py`, replace `from ancalagon.contracts.resolve import module_of` with `import importlib`, drop `import pathlib`, and change the first line of `accepts`:

```python
def accepts(ref: FunctionRef, args_model: type[pydantic.BaseModel], arity: int) -> str:
    module = importlib.import_module(ref.module)
```

In `ancalagon/tools/registry/resolve_before.py` and `resolve_after.py`, replace `from ancalagon.contracts.resolve import module_of` with `import importlib`, drop `import pathlib`, and change the lookup:

```python
    found = getattr(importlib.import_module(ref.module), ref.name)
```

- [ ] **Step 5: Make a config's own directory importable**

```python
# ancalagon/config/importable.py
# Puts a config file's own directory on the import path, so the modules it names resolve.
import pathlib
import sys


def importable(base: pathlib.PurePath) -> None:
    entry = str(base)
    if entry not in sys.path:
        sys.path.insert(0, entry)
```

In `ancalagon/config/load.py`: add `from ancalagon.config.importable import importable`, and call it as the second line of `load_config`, before anything reads a ref:

```python
def load_config(path: pathlib.PurePath, fs: FileSystem) -> Config:
    base = fs.resolve(path).parent
    importable(base)
    raw = tomllib.loads(fs.read_text(path))
```

`_class_ref` and `_hooks` stop rooting, and `_class_ref` loses its `base` and `fs` parameters:

```python
def _class_ref(raw: RawClassRef) -> ClassRef:
    return ClassRef(module=raw.module, name=raw.name)


def _hooks(
    raw: collections.abc.Mapping[str, collections.abc.Sequence[RawClassRef]],
) -> dict[str, tuple[FunctionRef, ...]]:
    return {
        tool: tuple(FunctionRef(module=ref.module, name=ref.name) for ref in refs)
        for tool, refs in raw.items()
    }
```

`_role` loses its `base` and `fs` parameters too, since nothing in it resolves a path any more:

```python
def _role(name: str, raw: RawRole) -> Role:
    if not ROLE_NAME.match(name):
        raise ValueError(
            f"[roles.{name}]: a role name becomes the tool name delegate_{name}, "
            f"so it must match {ROLE_NAME.pattern}"
        )
    return Role(
        behaviour=raw.behaviour,
        input=_class_ref(raw.input) if raw.input.module else FREE_TEXT,
        answer=_class_ref(raw.answer) if raw.answer.module else FREE_TEXT,
        tools=tuple(raw.tools),
        budget=Budget(turns=raw.budget.turns, tool_calls=raw.budget.tool_calls),
        before=_hooks(raw.before),
        after=_hooks(raw.after),
    )
```

and its call site in `load_config` becomes `_role(name, RawRole.model_validate(table))`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
```

Expected: PASS.

- [ ] **Step 7: Mutation-check the new refusal**

Temporarily change `DOTTED` to `r"^.*$"` and confirm `test_a_config_naming_a_file_path_is_refused_at_load` fails; temporarily remove the `importable(base)` call and confirm `test_roles_load_with_their_contracts_and_prose_is_the_absent_default` still passes but the equivalent test in Task 2 will not — note this and restore both. Then delete the `functools.cache` line from an old copy of `resolve.py` if you kept one; there should be nothing left of it.

- [ ] **Step 8: Move the untracked local configs over**

These are working-tree files, not tracked, so they are not part of the commit — but the harness will not run without them. Create a package for each loose helper module and rewrite the ten `module = ` lines:

```bash
uv run python - <<'PY'
import pathlib
for package, source in (("checkkit", "checks.py"), ("pongkit", "pong_checks.py")):
    made = pathlib.Path(package)
    made.mkdir(exist_ok=True)
    (made / "__init__.py").write_text("")
    (made / "checks.py").write_text(pathlib.Path(source).read_text())
    pathlib.Path(source).unlink()
PY
```

Then edit `ancalagon.toml`, `pong.toml`, `wake.toml` and `blackboard.toml`:

| Was | Becomes |
|---|---|
| `{ module = "./checks.py", name = … }` | `{ module = "checkkit.checks", name = … }` |
| `{ module = "./pong_checks.py", name = … }` | `{ module = "pongkit.checks", name = … }` |
| `{ module = "./ancalagon/contracts/watch_request.py", name = "WatchRequest" }` | `{ module = "ancalagon.contracts.watch_request", name = "WatchRequest" }` |
| `{ module = "./ancalagon/contracts/watched.py", name = "Watched" }` | `{ module = "ancalagon.contracts.watched", name = "Watched" }` |

Do not name a package after a run's write root: `pong/` already exists as `pong.toml`'s workspace, which is why the package is `pongkit`.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add ancalagon/contracts ancalagon/config ancalagon/tools/registry tests/unit
git commit -m "Refs name dotted modules, not file paths"
```

---

### Task 2: `Role.run` and derived contracts

**Files:**
- Create: `ancalagon/contracts/declared.py`, `ancalagon/contracts/no_run.py`, `ancalagon/contracts/run_contracts.py`
- Modify: `ancalagon/contracts/role.py`, `ancalagon/config/raw_role.py`, `ancalagon/config/load.py`, `ancalagon/tools/registry/accepts.py`
- Test: `tests/unit/test_config_load.py`

**Interfaces:**
- Consumes: `ClassRef`, `FunctionRef` with dotted `module` (Task 1).
- Produces: `ancalagon.contracts.declared.Declared = tuple[type[pydantic.BaseModel] | None, str]` and `declared(hints: collections.abc.Mapping[str, object], key: str, label: str) -> Declared`.
- Produces: `ancalagon.contracts.no_run.NO_RUN: FunctionRef` and `no_run() -> None`.
- Produces: `ancalagon.contracts.run_contracts.run_contracts(ref: FunctionRef) -> tuple[ClassRef, ClassRef]`, returning `(input, answer)`.
- Produces: `Role.run: FunctionRef`, defaulting to `NO_RUN`. Task 3 and Task 4 both read it.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_config_load.py`. One test for the whole behaviour, plus the module the run functions live in:

```python
RUNNERS = '''
import pydantic

from ancalagon.deterministic.run_context import RunContext


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    at: float


def good(given: Given, ctx: RunContext) -> Produced:
    return Produced(at=1.0)


def one_parameter(given: Given) -> Produced:
    return Produced(at=1.0)


def bare(given, ctx) -> Produced:
    return Produced(at=1.0)


def not_a_model(given: int, ctx: RunContext) -> Produced:
    return Produced(at=1.0)


def no_return(given: Given, ctx: RunContext):
    return Produced(at=1.0)


def returns_a_scalar(given: Given, ctx: RunContext) -> int:
    return 1
'''


def _with_run(tmp_path: pathlib.Path, name: str, extra: str = "") -> pathlib.Path:
    return _written(
        tmp_path,
        f"""
[roles.transformer]
behaviour = "Transform it."
run = {{ module = "runkit.runners", name = "{name}" }}
tools = []
budget = {{ turns = 0, tool_calls = 0 }}
{extra}
""",
    )


def test_a_role_naming_a_run_function_takes_its_contracts_from_the_signature(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "runkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "runners.py").write_text(RUNNERS)
    importable(tmp_path)

    role = load_config(_with_run(tmp_path, "good"), RealFileSystem()).roles["transformer"]

    assert role.run == FunctionRef(module="runkit.runners", name="good")
    assert role.input == ClassRef(module="runkit.runners", name="Given")
    assert role.answer == ClassRef(module="runkit.runners", name="Produced")

    prose = load_config(_written(tmp_path, PROSE_ROLE), RealFileSystem()).roles["scout"]
    assert prose.run == NO_RUN
    assert prose.input == FREE_TEXT

    def fault(name: str) -> str:
        with pytest.raises(ValueError) as raised:
            load_config(_with_run(tmp_path, name), RealFileSystem())
        return str(raised.value)

    assert fault("one_parameter") == (
        "one_parameter in runkit.runners must take 2 positional parameters, not ['given']"
    )
    assert "does not annotate its first parameter, given" in fault("bare")
    assert "annotates given as <class 'int'>, which is not a model class" in fault("not_a_model")
    assert "does not annotate its return" in fault("no_return")
    assert "annotates return as <class 'int'>, which is not a model class" in fault(
        "returns_a_scalar"
    )

    both = _with_run(
        tmp_path, "good", extra='answer = { module = "runkit.runners", name = "Produced" }'
    )
    with pytest.raises(ValueError, match="declares run"):
        load_config(both, RealFileSystem())


PROSE_ROLE = """
[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
"""
```

Note that `RUNNERS` imports `ancalagon.deterministic.run_context`, which Task 3 creates. Until then, annotate the second parameter as `pydantic.BaseModel` instead and change it to `RunContext` in Task 3 — nothing checks the second parameter's type, so the test asserts the same thing either way, and this keeps Task 2 independently committable.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run python -m pytest tests/unit/test_config_load.py::test_a_role_naming_a_run_function_takes_its_contracts_from_the_signature -v
```

Expected: FAIL with `pydantic_core.ValidationError` on the unknown `run` key, or `AttributeError: 'Role' object has no attribute 'run'`.

- [ ] **Step 3: Extract the shared annotation check**

```python
# ancalagon/contracts/declared.py
# Whether one annotation on a function names a model class, and what to say when it does not.
import collections.abc

import pydantic

Declared = tuple[type[pydantic.BaseModel] | None, str]


def declared(hints: collections.abc.Mapping[str, object], key: str, label: str) -> Declared:
    if key not in hints:
        return None, f"does not annotate {label}"
    found = hints[key]
    if not isinstance(found, type) or not issubclass(found, pydantic.BaseModel):
        return None, f"annotates {key} as {found}, which is not a model class"
    return found, ""
```

In `ancalagon/tools/registry/accepts.py`, delete the private `Declared` alias and `_declared`, import the shared pair, and change the one call:

```python
from ancalagon.contracts.declared import Declared, declared


def _annotation(found: collections.abc.Callable[..., object], arity: int) -> Declared:
    params = list(inspect.signature(found).parameters.values())
    if len(params) != arity or any(p.kind is not POSITIONAL for p in params):
        return None, f"must take {arity} positional parameters, not {[p.name for p in params]}"
    try:
        first = params[0].name
        return declared(typing.get_type_hints(found), first, f"its first parameter, {first}")
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"
```

Every message in `test_hooks.py` is preserved by this: `"does not annotate its first parameter, query"` comes from the label, `"annotates query as <class 'int'>, which is not a model class"` from the key.

- [ ] **Step 4: The absent run function**

```python
# ancalagon/contracts/no_run.py
# The run function a role served by a model names: there is not one.
from ancalagon.contracts.function_ref import FunctionRef


def no_run() -> None:
    raise NotImplementedError("this role is served by a model, not by a run function")


NO_RUN = FunctionRef(module="ancalagon.contracts.no_run", name="no_run")
```

This is the null object `FREE_TEXT` already is for contracts, and it exists because `None` is not available as a default. `no_run` takes no parameters, so a role that somehow reached the runner with it would be refused by the same arity check everything else is.

In `ancalagon/contracts/role.py`:

```python
from ancalagon.contracts.no_run import NO_RUN


class Role(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: ClassRef = FREE_TEXT
    answer: ClassRef = FREE_TEXT
    run: FunctionRef = NO_RUN
    tools: tuple[str, ...]
    budget: Budget
    before: collections.abc.Mapping[str, tuple[FunctionRef, ...]] = {}
    after: collections.abc.Mapping[str, tuple[FunctionRef, ...]] = {}
```

- [ ] **Step 5: Derive the contracts from the signature**

```python
# ancalagon/contracts/run_contracts.py
# The input and answer contracts a run function states in its own signature.
import importlib
import inspect
import typing

import pydantic

from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.declared import declared
from ancalagon.contracts.function_ref import FunctionRef

RUN_ARITY = 2
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD


def _ref_of(cls: type[pydantic.BaseModel]) -> ClassRef:
    return ClassRef(module=cls.__module__, name=cls.__name__)


def _must(
    hints: dict[str, object], key: str, label: str, ref: FunctionRef
) -> type[pydantic.BaseModel]:
    found, fault = declared(hints, key, label)
    if found is None:
        raise ValueError(f"{ref.name} in {ref.module} {fault}")
    return found


def run_contracts(ref: FunctionRef) -> tuple[ClassRef, ClassRef]:
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not callable(found):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    params = list(inspect.signature(found).parameters.values())
    if len(params) != RUN_ARITY or any(p.kind is not POSITIONAL for p in params):
        raise ValueError(
            f"{ref.name} in {ref.module} must take {RUN_ARITY} positional parameters, "
            f"not {[p.name for p in params]}"
        )
    hints = typing.get_type_hints(found)
    first = params[0].name
    given = _must(hints, first, f"its first parameter, {first}", ref)
    produced = _must(hints, "return", "its return", ref)
    return _ref_of(given), _ref_of(produced)
```

`found is None` is narrowing on a function that returns `None` to mean "not found", not a guard papering over a bug — `declared` returns the fault alongside it and `_must` is the only place that turns one into an exception.

- [ ] **Step 6: Wire it into the loader**

`ancalagon/config/raw_role.py` gains one field:

```python
class RawRole(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: RawClassRef = RawClassRef()
    answer: RawClassRef = RawClassRef()
    run: RawClassRef = RawClassRef()
    tools: list[str]
    budget: RawBudget
    before: dict[str, list[RawClassRef]] = {}
    after: dict[str, list[RawClassRef]] = {}
```

`RawClassRef` is reused rather than a `RawFunctionRef` added: it is already what `before` and `after` use for exactly this, two optional strings before anything is resolved.

`ancalagon/config/load.py:_role` splits into the declared case and the derived one:

```python
def _contracts(name: str, raw: RawRole) -> tuple[FunctionRef, ClassRef, ClassRef]:
    if not raw.run.module:
        return (
            NO_RUN,
            _class_ref(raw.input) if raw.input.module else FREE_TEXT,
            _class_ref(raw.answer) if raw.answer.module else FREE_TEXT,
        )
    if raw.input.module or raw.answer.module:
        raise ValueError(
            f"[roles.{name}]: a role that declares run states its contracts in that "
            f"function's signature, so it must not also declare input or answer"
        )
    ref = FunctionRef(module=raw.run.module, name=raw.run.name)
    given, produced = run_contracts(ref)
    return ref, given, produced


def _role(name: str, raw: RawRole) -> Role:
    if not ROLE_NAME.match(name):
        raise ValueError(
            f"[roles.{name}]: a role name becomes the tool name delegate_{name}, "
            f"so it must match {ROLE_NAME.pattern}"
        )
    run, given, produced = _contracts(name, raw)
    return Role(
        behaviour=raw.behaviour,
        input=given,
        answer=produced,
        run=run,
        tools=tuple(raw.tools),
        budget=Budget(turns=raw.budget.turns, tool_calls=raw.budget.tool_calls),
        before=_hooks(raw.before),
        after=_hooks(raw.after),
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v
```

Expected: PASS, including every message assertion in `test_hooks.py` unchanged.

- [ ] **Step 8: Mutation-check**

Break `run_contracts` in the two most obvious ways and confirm the test fails at the right assertion: return `(_ref_of(produced), _ref_of(given))` — the swapped contracts — and drop the `_must(hints, "return", …)` line so the answer defaults to the input. Restore both.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add ancalagon/contracts ancalagon/config ancalagon/tools/registry tests/unit
git commit -m "A role may name a run function, and states its contracts in that signature"
```

---

### Task 3: The deterministic runner

**Files:**
- Create: `ancalagon/deterministic/__init__.py`, `ancalagon/deterministic/run_context.py`, `ancalagon/deterministic/run.py`
- Modify: `ancalagon/supervisor/subprocess_spawner.py`, `ancalagon/cli.py`, `pyproject.toml`
- Test: `tests/unit/test_deterministic.py`, `tests/unit/test_sandbox.py`, `tests/integration/test_blackboard.py`

**Interfaces:**
- Consumes: `Role.run`, `NO_RUN`, `run_contracts` (Task 2); `importable` (Task 1).
- Produces: `RunContext(fs: FileSystem, clock: Clock, task_dir: pathlib.PurePath, run_dir: pathlib.PurePath)`, a frozen dataclass.
- Produces: `ancalagon.deterministic.run.Run`, a runtime-checkable protocol `__call__(self, given: pydantic.BaseModel, ctx: RunContext) -> pydantic.BaseModel`.
- Produces: `ancalagon.deterministic.run.resolve_run(ref: FunctionRef) -> Run`.
- Produces: `ancalagon.deterministic.run.main(run_dir, task_dir, agent_id, config_path) -> int`.
- Produces: `SubprocessSpawner(run_dir, config_path, environment, fs, module, sandbox)` — `module: str` is required, no default. Task 4 passes `"ancalagon.deterministic.run"` for the deterministic flavour.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_deterministic.py
import collections.abc
import json
import pathlib

from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.deterministic.run import main
from ancalagon.fs.real_file_system import RealFileSystem

RUNNERS = '''
import pydantic

from ancalagon.deterministic.run_context import RunContext


class Given(pydantic.BaseModel, frozen=True):
    path: str


class Produced(pydantic.BaseModel, frozen=True):
    seen: str


def echo(given: Given, ctx: RunContext) -> Produced:
    return Produced(seen=ctx.fs.read_text(ctx.task_dir / given.path))


def explodes(given: Given, ctx: RunContext) -> Produced:
    raise RuntimeError("the transform gave up")
'''

CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "fence"

[run]
goal_file = ""
input_file = ""
role = "transformer"

[roles.transformer]
behaviour = "Read the file you are given."
run = { module = "runkit.runners", name = "%s" }
tools = []
budget = { turns = 0, tool_calls = 0 }
"""


def _prepared(
    tmp_path: pathlib.Path,
    importable: collections.abc.Callable[[pathlib.Path], None],
    function: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    package = tmp_path / "runkit"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "runners.py").write_text(RUNNERS)
    importable(tmp_path)
    config_path = tmp_path / f"{function}.toml"
    config_path.write_text(CONFIG % function)
    task_dir = tmp_path / "tasks" / function
    task_dir.mkdir(parents=True)
    role = load_config(config_path, RealFileSystem()).roles["transformer"]
    given = importlib.import_module("runkit.runners").Given(path="board.md")
    spec = AgentSpec[type(given)](
        task_id=function, role=role, goal="Read it.", input=given
    )
    (task_dir / "spec.json").write_text(spec.model_dump_json())
    return config_path, task_dir


def test_a_run_function_produces_the_outcome_a_supervisor_reads(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "echo")
    (task_dir / "board.md").write_text("a claim appeared")

    assert main(tmp_path, task_dir, 4, config_path) == 0

    written = json.loads((task_dir / "outcome-4.json").read_text())
    assert written["kind"] == "completed"
    assert written["value"] == {"seen": "a claim appeared"}
    assert written["summary"] == '{"seen":"a claim appeared"}'
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert sorted(p.name for p in task_dir.iterdir()) == [
        "board.md",
        "outcome-4.json",
        "spec.json",
    ]


def test_a_run_function_that_raises_records_a_failure_the_way_a_worker_does(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    config_path, task_dir = _prepared(tmp_path, importable, "explodes")

    assert main(tmp_path, task_dir, 9, config_path) == 1

    written = json.loads((task_dir / "outcome-9.json").read_text())
    assert written["kind"] == "failed"
    assert written["summary"] == "the transform gave up"
    assert "RuntimeError: the transform gave up" in written["error"]
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
```

`importlib` joins the imports at the top of the file. The test builds its spec from the same package the config names, which is what makes the ref in `spec.json` resolvable inside `main`.

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run python -m pytest tests/unit/test_deterministic.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.deterministic'`.

- [ ] **Step 3: The context**

```python
# ancalagon/deterministic/run_context.py
# What a run function is given besides its input: the ports, and where this task lives.
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
```

A frozen dataclass rather than a model: `FileSystem` and `Clock` are protocols, and nothing here crosses a wire.

Create an empty `ancalagon/deterministic/__init__.py`.

- [ ] **Step 4: The runner**

```python
# ancalagon/deterministic/run.py
# A child that runs one Python function instead of a session. The contract with the
# supervisor is the worker's: read spec.json, write outcome-<agent>.json.
import argparse
import importlib
import pathlib
import sys
import traceback
import typing

import pydantic

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.importable import importable
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.outcome import SUMMARY_CHARS
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.deterministic.run_context import RunContext
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem

NOTHING = Budget(turns=0, tool_calls=0)


@typing.runtime_checkable
class Run(typing.Protocol):
    def __call__(self, given: pydantic.BaseModel, ctx: RunContext) -> pydantic.BaseModel: ...


def resolve_run(ref: FunctionRef) -> Run:
    found = getattr(importlib.import_module(ref.module), ref.name)
    if not isinstance(found, Run):
        raise ValueError(f"{ref.name} in {ref.module} is not callable")
    return found


def _completed(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    config_path: pathlib.PurePath,
    fs: FileSystem,
) -> Completed[pydantic.BaseModel]:
    importable(fs.resolve(config_path).parent)
    spec_text = fs.read_text(task_dir / "spec.json")
    spec = TaskSpec.model_validate_json(spec_text)
    input_class = resolve_class(spec.role.input)
    given = AgentSpec[input_class].model_validate_json(spec_text).input
    ctx = RunContext(fs=fs, clock=SystemClock(), task_dir=task_dir, run_dir=run_dir)
    produced = resolve_run(spec.role.run)(given, ctx)
    return Completed(
        value=produced, summary=produced.model_dump_json()[:SUMMARY_CHARS], spent=NOTHING
    )


def main(
    run_dir: pathlib.PurePath,
    task_dir: pathlib.PurePath,
    agent_id: int,
    config_path: pathlib.PurePath,
) -> int:
    fs = RealFileSystem()
    outcome_path = task_dir / f"outcome-{agent_id}.json"
    try:
        produced = _completed(run_dir, task_dir, config_path, fs)
        fs.write_text(outcome_path, produced.model_dump_json())
        return 0
    except Exception as exc:
        failure = Failed(
            error=traceback.format_exc(), summary=str(exc)[:SUMMARY_CHARS], spent=NOTHING
        )
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon.deterministic.run")
    parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--dir", type=pathlib.PurePath, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.PurePath, required=True)
    args = parser.parse_args()
    return main(args.run_dir, args.dir, args.agent_id, args.config)


if __name__ == "__main__":
    sys.exit(cli())
```

`importable` is called here rather than a whole config being loaded, because the config file is wanted for exactly one thing: making the modules it names resolvable. The worker and the CLI get the same call for free by loading a config at all.

`AgentSpec[input_class]` where `input_class` is a runtime value is the same subscript `worker.py:170` already uses; if Pyright complains, match what `worker.py` does at that line and nothing more.

- [ ] **Step 5: Parameterise the spawner by its module**

In `ancalagon/supervisor/subprocess_spawner.py`, the header comment becomes `# The only place in the codebase that starts an OS process.` (unchanged), and `module` joins the constructor as a required argument placed before `sandbox`:

```python
class SubprocessSpawner(Spawner):
    def __init__(
        self,
        run_dir: pathlib.PurePath,
        config_path: pathlib.PurePath,
        environment: Environment,
        fs: FileSystem,
        module: str,
        sandbox: Sandbox = UNSANDBOXED,
    ):
        self.run_dir = run_dir
        self.config_path = config_path
        self.environment = environment
        self.fs = fs
        self.module = module
        self.sandbox = sandbox

    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        self.fs.mkdir(stderr.parent, parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            self.module,
            "--run-dir",
            str(self.run_dir),
            "--dir",
            str(task_dir),
            "--agent-id",
            str(agent_id),
            "--config",
            str(self.config_path),
        ]
        return subprocess.Popen(
            list(self.sandbox.wrap(command)),
            stdout=subprocess.DEVNULL,
            stderr=self.fs.open_write(stderr),
            cwd=self.run_dir,
            env=inherited(self.environment, self.sandbox),
        )
```

It is required rather than defaulted to `"ancalagon.worker"`, so both flavours say which one they are at the point they are built. Update the three construction sites — `ancalagon/cli.py:182`, `tests/unit/test_sandbox.py:65`, `tests/integration/test_blackboard.py:54` — to pass `module="ancalagon.worker"`.

- [ ] **Step 6: Register the new package with import-linter**

In `pyproject.toml`, add `"ancalagon.deterministic"` to the `source_modules` list of the contract named `SQL stays in the adapters` and to the one named `The process is reached only by the adapters that own it`, keeping both lists alphabetical — it goes immediately after `"ancalagon.contracts"`.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit -v && uv run lint-imports
```

Expected: PASS, seven contracts kept.

- [ ] **Step 8: Mutation-check**

Break the runner in the two most obvious ways and confirm the right test fails: change `summary=produced.model_dump_json()[:SUMMARY_CHARS]` to `summary=""` (the completed test fails on the summary assertion), and change the `except Exception` block to re-raise (the failure test errors instead of asserting `kind == "failed"`). Restore both.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
git add ancalagon/deterministic ancalagon/supervisor ancalagon/cli.py pyproject.toml tests
git commit -m "A child that runs a Python function instead of a session"
```

---

### Task 4: Collapse the watcher into the general case

**Files:**
- Create: `ancalagon/watch/watch_for.py`, `ancalagon/supervisor/spawn_by_run.py`
- Delete: `ancalagon/watch/watch.py`, `ancalagon/supervisor/watch_spawner.py`, `ancalagon/supervisor/spawn_by_input.py`
- Modify: `ancalagon/cli.py`, `README.md`, `docs/architecture.md`
- Test: `tests/unit/test_watch.py`, `tests/integration/test_blackboard.py`

**Interfaces:**
- Consumes: `RunContext`, `SubprocessSpawner(..., module=...)` (Task 3); `Role.run`, `NO_RUN` (Task 2).
- Produces: `ancalagon.watch.watch_for.watch_for(request: WatchRequest, ctx: RunContext) -> Watched`.
- Produces: `SpawnByRun(default: Spawner, deterministic: Spawner, fs: FileSystem)`.

- [ ] **Step 1: Rewrite the failing tests**

In `tests/unit/test_watch.py`:

`test_a_watcher_waits_until_the_file_it_was_given_changes` keeps its `WritingClock` and changes only how the function is called:

```python
from ancalagon.deterministic.run_context import RunContext
from ancalagon.watch.watch_for import watch_for


def test_a_watcher_waits_until_the_file_it_was_given_changes(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    board = tmp_path / "blackboard.md"
    board.write_text("first\n")
    before = fs.changed_at(board)
    clock = WritingClock(board, after=3)
    ctx = RunContext(fs=fs, clock=clock, task_dir=tmp_path, run_dir=tmp_path)

    watched = watch_for(WatchRequest(path=str(board), since=before), ctx)

    assert clock.slept == 3
    assert watched.path == str(board)
    assert watched.at > before
```

`test_a_watcher_leaves_the_outcome_a_supervisor_reads_and_nothing_else` and `test_a_watcher_records_a_failure_the_way_a_worker_does` are **deleted**: `tests/unit/test_deterministic.py` covers both behaviours for every run function, watcher included, and keeping watcher-shaped copies would assert the template twice.

`test_a_dispatching_spawner_picks_the_watcher_by_the_contract_the_role_declares` is replaced by one that asks the question the new dispatcher asks:

```python
def test_a_dispatching_spawner_picks_the_runner_when_the_role_names_a_run_function(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    asked: list[tuple[str, pathlib.PurePath]] = []

    class Noting(Spawner):
        def __init__(self, label: str):
            self.label = label

        def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
            asked.append((self.label, task_dir))
            return FakeProcess()

    def task(name: str, run: FunctionRef) -> pathlib.PurePath:
        made = tmp_path / name
        made.mkdir(parents=True, exist_ok=True)
        spec = AgentSpec[FreeText](
            task_id=name,
            role=ROLE.model_copy(update={"run": run}),
            goal="g",
            input=FreeText(text="t"),
        )
        fs.write_text(made / "spec.json", spec.model_dump_json())
        return made

    watching = FunctionRef(module="ancalagon.watch.watch_for", name="watch_for")
    dispatch = SpawnByRun(
        default=Noting("worker"), deterministic=Noting("runner"), fs=fs
    )

    dispatch.spawn(task("a", watching), 1)
    dispatch.spawn(task("b", NO_RUN), 2)

    assert [label for label, _ in asked] == ["runner", "worker"]
```

`test_watch_file_is_offered_only_where_a_role_declares_the_watch_contract` is unchanged except for the deleted `WATCHES` constant already handled in Task 1: `watcher_in` in `worker.py:113` still asks `role.input.name == "WatchRequest"`, and derivation makes that true for a role naming `watch_for`. Do not change `watcher_in`.

In `tests/integration/test_blackboard.py`, the role built at line 40 gains a `run` and loses its `input`:

```python
        role=Role(
            behaviour="Wait for the blackboard.",
            run=FunctionRef(module="ancalagon.watch.watch_for", name="watch_for"),
            input=WATCHING,
            tools=(),
            budget=Budget(turns=0, tool_calls=0),
        ),
```

`input` stays here because this test builds the `Role` in Python rather than through `load_config`, and the runner resolves `role.input` to validate the spec. Derivation is a loader concern; a `Role` constructed directly must still state what it holds.

`WatchSpawner` is replaced:

```python
    watching = SubprocessSpawner(
        run_dir=run_dir,
        config_path=tmp_path / "unused.toml",
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.deterministic.run",
        sandbox=Unsandboxed(),
    )
```

and the supervisor takes `spawner=SpawnByRun(default=ordinary, deterministic=watching, fs=fs)`. The config path is no longer ignored — `_completed` calls `importable` on its parent — so write the file before the supervisor runs, and rename it for what it now does:

```python
    (tmp_path / "watcher.toml").write_text("")
```

passing `config_path=tmp_path / "watcher.toml"` to both spawners. Its contents are never read; only its directory is, and `ancalagon.watch.watch_for` is on the import path already.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run python -m pytest tests/unit/test_watch.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.watch.watch_for'` and `ImportError` on `SpawnByRun`.

- [ ] **Step 3: The run function alone**

```python
# ancalagon/watch/watch_for.py
# Waits for a file to change, then ends. The whole of a watcher.
import pathlib

from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched
from ancalagon.deterministic.run_context import RunContext


def watch_for(request: WatchRequest, ctx: RunContext) -> Watched:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    return Watched(path=request.path, at=ctx.fs.changed_at(watched))
```

Delete `ancalagon/watch/watch.py`.

- [ ] **Step 4: Dispatch on the run function**

```python
# ancalagon/supervisor/spawn_by_run.py
# Chooses which kind of process a task gets: a role that names a run function is served
# by one, and every other role by a session.
import pathlib

from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner


class SpawnByRun(Spawner):
    def __init__(self, default: Spawner, deterministic: Spawner, fs: FileSystem):
        self.default = default
        self.deterministic = deterministic
        self.fs = fs

    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
        spec = TaskSpec.model_validate_json(self.fs.read_text(task_dir / "spec.json"))
        chosen = self.default if spec.role.run == NO_RUN else self.deterministic
        return chosen.spawn(task_dir, agent_id)
```

Delete `ancalagon/supervisor/spawn_by_input.py` and `ancalagon/supervisor/watch_spawner.py`.

- [ ] **Step 5: Rewrite the CLI's spawner**

In `ancalagon/cli.py`, drop the `WatchSpawner`, `SpawnByInput` and `WatchRequest` imports, add `SpawnByRun`, and replace `_spawner` and the comment above it:

```python
# A task whose role names a run function is served by a process, not by a model, so the
# supervisor is given a spawner that reads each spec and picks accordingly.
def _spawner(
    config: Config, run_dir: pathlib.PurePath, config_path: pathlib.PurePath, fs: FileSystem
) -> Spawner:
    made = fs.resolve(config_path)
    sandbox = sandbox_of(config, run_dir, fs)
    ordinary = SubprocessSpawner(
        run_dir=run_dir,
        config_path=made,
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.worker",
        sandbox=sandbox,
    )
    deterministic = SubprocessSpawner(
        run_dir=run_dir,
        config_path=made,
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.deterministic.run",
        sandbox=sandbox,
    )
    return SpawnByRun(default=ordinary, deterministic=deterministic, fs=fs)
```

`config` is still a parameter because `sandbox_of` takes it.

- [ ] **Step 6: Move the untracked configs to `run`**

In `wake.toml` and `blackboard.toml`, the watcher role's two contract lines become one:

```toml
run = { module = "ancalagon.watch.watch_for", name = "watch_for" }
```

Delete its `input` and `answer` lines — declaring either alongside `run` is now an error.

- [ ] **Step 7: Run everything to verify it passes**

```bash
uv run python -m pytest tests/unit -v
uv run python -m pytest tests/integration/test_blackboard.py -v
```

Expected: PASS. `test_blackboard.py` is what proves the collapse end to end — a real supervisor, a real process, a role whose only declaration is a run function.

- [ ] **Step 8: Update the living docs**

`docs/architecture.md:345-346`: replace

> `SpawnByInput` chooses between flavours by reading the input contract a role declares, which is already in `spec.json` and already validated at startup. `Spawner` stays the protocol it was.

with a paragraph saying that `SpawnByRun` chooses between flavours by asking whether the role names a run function, that the function states its own input and answer contracts and the loader fills the role's from that signature, and that `Spawner` stays the protocol it was.

`README.md:232-234`: the sentence beginning "`watch_file` is the one that needs something else declared: a role whose `input` contract is `WatchRequest`" is still true — derivation makes it true — but should now say that such a role is declared by naming `watch_for` as its `run` function, and that the input contract follows from the signature. Add a short subsection to the roles documentation showing the deterministic role in full:

```toml
[roles.watcher]
behaviour = "Wait for the blackboard to change."
run = { module = "ancalagon.watch.watch_for", name = "watch_for" }
tools = []
budget = { turns = 0, tool_calls = 0 }
```

and stating the rule: two positional parameters, the first annotated with the input contract and the second `RunContext`, and a return annotation naming the answer contract; a role that declares `run` must not declare `input` or `answer`.

- [ ] **Step 9: Grep for what a rename leaves behind**

```bash
grep -rn "SpawnByInput\|WatchSpawner\|by_input\|ancalagon.watch.watch\b\|watch_request.py\|watched.py" \
  --include="*.py" --include="*.toml" --include="*.md" . | grep -v "\.venv"
```

Expected: no hits outside `docs/superpowers/` (the specs and plans are immutable and keep their historical wording).

- [ ] **Step 10: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
uv run python -m pytest tests/integration/test_blackboard.py
git add -A ancalagon tests README.md docs/architecture.md
git commit -m "The watcher is a run function, and the harness runs it like any other"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the run function and `RunContext` to Task 3; dotted refs, the `sys.path` insertion and the per-run packages to Task 1; derivation at load and the rejection of deriving in `delegate_tools` to Task 2; the runner, `ModuleSpawner` and `SpawnByRun` to Tasks 3 and 4; the import-linter registration to Task 3 step 6; the "what is deleted" list to Task 4. The spec calls the parameterised spawner `ModuleSpawner`; this plan parameterises `SubprocessSpawner` itself instead, because a second class differing by one constructor argument is the duplication the spec set out to remove. The spec puts the `sys.path` insertion in `load_config`; this plan keeps one implementation, `config.importable`, called by `load_config` and by the deterministic runner, which loads no config.

**Delegation.** The spec's "delegation is unchanged" section has no task because it requires no change: `delegate_tools`, `DelegateTo`, `check_task` and `collect_task` are untouched by every task here. Task 4 step 9's grep is what confirms it.

**Types.** `run_contracts` returns `tuple[ClassRef, ClassRef]` in Task 2 and is consumed as `given, produced = run_contracts(ref)` in `_contracts`; `resolve_run` returns `Run` in Task 3 and is called as `resolve_run(spec.role.run)(given, ctx)`; `SubprocessSpawner`'s `module` is a required `str` in Task 3 and passed by keyword at all four sites in Tasks 3 and 4; `RunContext`'s four fields are named identically in `run.py`, `watch_for.py` and both test files.
