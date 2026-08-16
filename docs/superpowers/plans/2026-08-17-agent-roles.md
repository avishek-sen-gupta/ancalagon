# Agent Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace model-authored contracts with roles declared in configuration, so an agent's behaviour, contracts, tools and budget are decided before the run rather than guessed during it.

**Architecture:** A `Role` is a frozen model naming a behaviour, an input contract, an answer contract, a tool list and a budget. Roles are declared under `[roles.*]` in the config. Each role a worker may spawn becomes its own `delegate_<role>` tool whose argument model is built at startup with `create_model`, so the parent sees that role's real input schema instead of a JSON string. `spec.json` embeds the whole `Role`, freezing a task's terms when it is queued.

**Tech Stack:** Python 3.13, Pydantic v2 (`create_model`, frozen models), tomllib, pytest, Pyright strict.

**Spec:** `docs/superpowers/specs/2026-08-17-agent-roles-design.md`

## Global Constraints

- Pyright runs in strict mode and must pass with **zero errors**. `Any` is banned outright — no `from typing import Any`, no `: Any`, no `dict[str, Any]`. `object` and JSON-blob types are banned for the same reason.
- Every generic must be parameterised: `dict[str, int]`, never bare `dict`; `Mapping[str, Role]`, never bare `Mapping`.
- **No comments** except a one-line header on a class or module stating its purpose. No docstrings, no inline explanations, no section dividers, no TODOs.
- Dataclasses and Pydantic models are `frozen=True`. No exceptions.
- A class implementing a `Protocol` **inherits** it, so the error lands on the broken class rather than on a distant list.
- Fully qualified imports, no relative imports. One class per file.
- `Sequence`/`Mapping` from `collections.abc` for parameters that are not mutated — never `list`/`dict` in such a signature.
- No `None` defaults, no `None` returns from non-`None` return types, no defensive `isinstance` checks, no bare `except`.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a new file. Assert concrete values (`assert result == 30`), never `assert x is not None`.
- **No mocking.** `unittest.mock.patch` is banned. Use injected fakes — `FakeLLM`, `FakeClock`, fake spawners.
- Text is a boundary, never a carrier: JSON becomes a Pydantic model via `model_validate_json` the moment it arrives, and is serialised only at the wire or a file write.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit`.
- The repo's pre-commit hook includes a `python-fp-lint` gate failing on roughly a dozen **pre-existing** findings (import ordering, ambiguous `l` names). If it fails only on findings your diff did not introduce, commit with `--no-verify` and say so in the commit message. Never use `--no-verify` to hide a failure your own change caused.
- Never reference an external codebase (names, APIs, domains, packages) in any tracked artifact. Use `com.example.utils`, `class Foo`.

---

## File Structure

**Created**

- `ancalagon/contracts/role.py` — `Role`, the frozen model bound to a name in config.
- `ancalagon/tools/delegate/delegate_to.py` — `DelegateTo`, the one hand-written delegate class; one instance per role.
- `ancalagon/tools/delegate/delegate_args.py` — rewritten as the static base (`task_id`, `goal`, `input: BaseModel`) that `create_model` overrides per role.
- `ancalagon/tools/delegate/delegate_tools.py` — `delegate_tools(roles, run_dir, parent, clock)`, building one `BoundTool` per role.

**Modified**

- `ancalagon/contracts/class_ref.py` — `module` becomes a path, losing the filename pattern.
- `ancalagon/contracts/resolve.py` — `resolve_class(ref)` loses its `base` parameter and the escape check.
- `ancalagon/contracts/agent_spec.py` / `task_spec.py` — down to `task_id`, `role`, `goal`, (`input`).
- `ancalagon/contracts/run_settings.py` — `role` and `input_file` replace `contract_module`/`contract_class`.
- `ancalagon/config/config.py` / `load.py` — `roles` added; `root_behaviour` and `tools` removed.
- `ancalagon/worker.py` — registry built from the spec's role plus config roles.
- `ancalagon/session.py` — reads `spec.role.behaviour` and `spec.role.budget`.
- `ancalagon/cli.py` — root spec built from a role; `install_contracts`, `contract_source`, `answer_schema_of` deleted.

**Deleted**

`ancalagon/contracts/contract_pair.py`, `contract_source.py`, `allowance.py`, `within_parent.py`, `as_asked.py`, `free_text_ref.py`, `free_text_module.py`, `ancalagon/tools/delegate/delegate.py`.

---

### Task 1: `Role`, and contract references that name a path

**Files:**
- Create: `ancalagon/contracts/role.py`
- Modify: `ancalagon/contracts/class_ref.py`, `ancalagon/contracts/resolve.py`
- Modify (callers): `ancalagon/worker.py:120-121`, `ancalagon/tools/delegate/collect_task.py:53`, `ancalagon/cli.py`
- Test: `tests/unit/test_contracts.py`

**Interfaces:**
- Produces: `Role(behaviour: str, input: ClassRef, answer: ClassRef, tools: tuple[str, ...], budget: Budget)`; `ClassRef(module: str, name: str)` where `module` is a filesystem path; `resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]`.

`ClassRef.module` currently carries a bare filename constrained to `^[A-Za-z_][A-Za-z0-9_]*\.py$`, because a model supplied it and `resolve_class` refused anything outside the task directory. With roles the path comes from config, so both the pattern and the escape check go. `FreeText` is no longer written into task directories, so `FREE_TEXT_REF` and `FREE_TEXT_MODULE` are deleted here and `Role` defaults its contracts to the installed `FreeText`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_contracts.py`:

```python
def test_a_role_defaults_to_prose_and_resolves_the_contracts_it_names(tmp_path: pathlib.Path):
    module = tmp_path / "shapes.py"
    module.write_text(
        "import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n"
    )

    prose = Role(behaviour="Investigate.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8))
    assert resolve_class(prose.input) is FreeText
    assert resolve_class(prose.answer) is FreeText

    named = Role(
        behaviour="Analyse.",
        answer=ClassRef(module=str(module), name="Component"),
        tools=("read_file",),
        budget=Budget(turns=4, tool_calls=8),
    )
    assert resolve_class(named.answer).model_fields.keys() == {"name"}
    assert resolve_class(named.input) is FreeText

    with pytest.raises(AttributeError):
        resolve_class(ClassRef(module=str(module), name="Absent"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_contracts.py -k role -v`
Expected: FAIL with `ImportError: cannot import name 'Role'`

- [ ] **Step 3: Write `Role`**

`ancalagon/contracts/role.py`:

```python
# Everything about an agent except its task: what it is told, what it works to, what it may use.
import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef

FREE_TEXT = ClassRef(module="ancalagon/contracts/free_text.py", name="FreeText")


class Role(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: ClassRef = FREE_TEXT
    answer: ClassRef = FREE_TEXT
    tools: tuple[str, ...]
    budget: Budget
```

- [ ] **Step 4: Loosen `ClassRef` and simplify `resolve_class`**

`ancalagon/contracts/class_ref.py` — the header changes because the type no longer means what it did:

```python
# Names one contract class by the module path that defines it.
import pydantic


class ClassRef(pydantic.BaseModel, frozen=True):
    module: str
    name: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
```

`ancalagon/contracts/resolve.py`:

```python
# Imports a contract module by the path its ClassRef names.
import importlib.util
import pathlib
import sys

import pydantic

from ancalagon.contracts.class_ref import ClassRef


def resolve_class(ref: ClassRef) -> type[pydantic.BaseModel]:
    path = pathlib.Path(ref.module).resolve()
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    resolved = getattr(module, ref.name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{ref.name} in {ref.module} is not a pydantic model")
    return resolved
```

`FREE_TEXT` names `ancalagon/contracts/free_text.py` relative to the working directory, which is the run directory. Make it absolute so it resolves from anywhere:

```python
FREE_TEXT = ClassRef(
    module=str(pathlib.Path(ancalagon.contracts.free_text.__file__)), name="FreeText"
)
```

- [ ] **Step 5: Update the three callers**

`worker.py:120-121` becomes `resolve_class(spec.role.answer)` and `resolve_class(spec.role.input)` in Task 4; for now change only the call shape, dropping `task_dir`. Same for `collect_task.py:53`. Delete `ancalagon/contracts/free_text_ref.py` and `free_text_module.py` and fix the imports Pyright reports.

- [ ] **Step 6: Verify**

Run: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit`
Expected: 0 Pyright errors, all tests pass.

- [ ] **Step 7: Mutation-check**

Change `Role.input`'s default to `Role.answer`'s value and confirm nothing fails — if nothing does, the test is not distinguishing them and must be strengthened. Then remove the `issubclass` check in `resolve_class` and confirm the `AttributeError` case still fails for the right reason. Restore both.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "A contract reference names a path, and a role names contracts"
```

---

### Task 2: `[roles.*]` in the config

**Files:**
- Modify: `ancalagon/config/config.py`, `ancalagon/config/load.py`
- Test: `tests/unit/test_config_load.py`

**Interfaces:**
- Consumes: `Role` from Task 1.
- Produces: `Config.roles: Mapping[str, Role]`; `Config` no longer has `root_behaviour` or `tools`.

Every key is read by bracket, never `.get()`, so a config file must be complete — `Config`'s defaults exist for callers building one in code. Optional *role* keys are the exception: `input` and `answer` may be absent, meaning `FreeText`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config_load.py`:

```python
def test_roles_load_with_their_contracts_and_prose_is_the_absent_default(tmp_path: pathlib.Path):
    shapes = tmp_path / "shapes.py"
    shapes.write_text("import pydantic\n\n\nclass Component(pydantic.BaseModel):\n    name: str\n")
    config = _written(
        tmp_path,
        """
[roles.analyst]
behaviour = "Analyse."
answer = { module = "./shapes.py", name = "Component" }
tools = ["read_file", "delegate_scout"]
budget = { turns = 12, tool_calls = 30 }

[roles.scout]
behaviour = "Investigate."
tools = ["read_file"]
budget = { turns = 4, tool_calls = 8 }
""",
    )

    roles = load_config(config).roles

    assert sorted(roles) == ["analyst", "scout"]
    assert roles["analyst"].behaviour == "Analyse."
    assert roles["analyst"].answer == ClassRef(module=str(shapes), name="Component")
    assert roles["analyst"].tools == ("read_file", "delegate_scout")
    assert roles["analyst"].budget == Budget(turns=12, tool_calls=30)
    assert roles["scout"].answer == FREE_TEXT
    assert roles["scout"].input == FREE_TEXT
```

`_written` is a helper this test file needs: it writes a complete config with the given block appended. Follow the existing fixture style in that file rather than inventing a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_config_load.py -k roles -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'roles'`

- [ ] **Step 3: Add `roles` to `Config`, remove `root_behaviour` and `tools`**

In `ancalagon/config/config.py`, delete the `ROOT_BEHAVIOUR` constant, the `root_behaviour` field and the `tools` field, and add:

```python
    roles: collections.abc.Mapping[str, Role] = {}
```

- [ ] **Step 4: Parse `[roles.*]` in `load.py`**

```python
def _class_ref(base: pathlib.Path, raw: collections.abc.Mapping[str, str]) -> ClassRef:
    return ClassRef(module=str(_root(base, raw["module"])), name=raw["name"])


def _role(base: pathlib.Path, raw: RawRole) -> Role:
    return Role(
        behaviour=raw.behaviour,
        input=_class_ref(base, raw.input) if raw.input else FREE_TEXT,
        answer=_class_ref(base, raw.answer) if raw.answer else FREE_TEXT,
        tools=tuple(raw.tools),
        budget=Budget(turns=raw.budget["turns"], tool_calls=raw.budget["tool_calls"]),
    )
```

`raw` arrives from `tomllib` as nested dicts, which the guardrails forbid indexing. Parse it into a model at the boundary — add `ancalagon/config/raw_role.py`:

```python
# One [roles.*] table exactly as TOML presents it, before paths are resolved.
import pydantic


class RawRole(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: dict[str, str] = {}
    answer: dict[str, str] = {}
    tools: list[str]
    budget: dict[str, int]
```

then in `load_config`:

```python
        roles={
            name: _role(base, RawRole.model_validate(table))
            for name, table in raw.get("roles", {}).items()
        },
```

`raw.get` is used here and only here: `[roles]` may legitimately be absent while a config is still complete, unlike every other section.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_config_load.py -k roles -v`
Expected: PASS

- [ ] **Step 6: Fix the fallout**

`load.py` no longer reads `raw["agent"]["root_behaviour"]` or `raw["tools"]["enabled"]`. Every config fixture in `tests/` that contains `[agent]` or `[tools]` must lose those sections; Pyright and the test run will name them.

- [ ] **Step 7: Verify and mutation-check**

Run the full unit suite. Then change `_role` to pass `FREE_TEXT` for `answer` unconditionally and confirm the new test fails on the `analyst` assertion. Restore.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Declare roles in the config, and stop declaring a root behaviour"
```

---

### Task 3: One delegate tool per role

**Files:**
- Create: `ancalagon/tools/delegate/delegate_to.py`, `ancalagon/tools/delegate/delegate_tools.py`
- Rewrite: `ancalagon/tools/delegate/delegate_args.py`
- Delete: `ancalagon/tools/delegate/delegate.py`, `ancalagon/contracts/contract_pair.py`, `ancalagon/contracts/contract_source.py`, `ancalagon/contracts/allowance.py`, `ancalagon/contracts/within_parent.py`, `ancalagon/contracts/as_asked.py`
- Test: `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `Role` (Task 1), `Config.roles` (Task 2).
- Produces: `delegate_tools(roles: Mapping[str, Role], run_dir: pathlib.Path, parent: int, clock: Clock) -> list[BoundTool]`, each named `delegate_<role>`.

This task writes `spec.json` with the *old* `AgentSpec` field set, keeping `behaviour`, `input_schema`, `answer_schema` and `budget` sourced from the role. Task 4 shrinks `AgentSpec`. Splitting them keeps each commit's diff reviewable.

- [ ] **Step 1: Write the failing test**

```python
def test_a_delegate_tool_exists_per_role_and_shows_that_role_s_input_schema(
    tmp_path: pathlib.Path,
):
    shapes = tmp_path / "shapes.py"
    shapes.write_text(
        "import pydantic\n\n\nclass Query(pydantic.BaseModel):\n    area: str\n    depth: int\n"
    )
    roles = {
        "analyst": Role(
            behaviour="Analyse.",
            input=ClassRef(module=str(shapes), name="Query"),
            tools=("read_file",),
            budget=Budget(turns=12, tool_calls=30),
        ),
        "scout": Role(behaviour="Look.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8)),
    }
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version())

    tools = delegate_tools(roles, run_dir=run_dir, parent=1, clock=FakeClock())

    assert [t.name for t in tools] == ["delegate_analyst", "delegate_scout"]
    shown = tools[0].declaration.parameters.model_json_schema()
    assert sorted(shown["properties"]) == ["goal", "input", "task_id"]
    assert sorted(shown["$defs"]["Query"]["properties"]) == ["area", "depth"]

    ctx = _ctx(tmp_path)
    ok = tools[0].invoke(
        '{"task_id": "t1", "goal": "map the bus", "input": {"area": "bus", "depth": 2}}', ctx
    )
    assert ok.ok is True
    spec = json.loads((run_dir / "tasks" / "t1" / "spec.json").read_text())
    assert spec["goal"] == "map the bus"
    assert spec["input"] == {"area": "bus", "depth": 2}
    assert spec["budget"] == {"turns": 12, "tool_calls": 30}

    bad = tools[0].invoke('{"task_id": "t2", "goal": "g", "input": {"area": "bus"}}', ctx)
    assert bad.ok is False
    assert "depth" in bad.error
```

The last two lines are the point of the whole change: a payload missing a field is refused with the field named, rather than accepted as a string and discovered later.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_tools.py -k delegate_tool -v`
Expected: FAIL with `ImportError: cannot import name 'delegate_tools'`

- [ ] **Step 3: Rewrite `DelegateArgs` as the static base**

```python
# The fields every delegate tool takes; create_model narrows `input` per role.
import pydantic


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    goal: str
    input: pydantic.BaseModel
```

`input: pydantic.BaseModel` is legal here and nowhere else: the subclass `create_model` builds always overrides the annotation with a concrete class, so nothing is ever validated or serialised against the base. This was verified — a base-class override yields a real `Query` on parse, shows `area` and `depth` in the schema, and rejects a payload missing `depth`.

- [ ] **Step 4: Write `DelegateTo`**

```python
# Queues one task for one role; the supervisor spawns it.
import pathlib

import pydantic

from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class DelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(self, role_name: str, role: Role, run_dir: pathlib.Path, parent: int, clock: Clock):
        self.name = f"delegate_{role_name}"
        self.description = (
            f"Queue a {role_name} task. Returns its task id immediately without waiting. "
            f"That agent is told: {role.behaviour}"
        )
        self.role = role
        self.run_dir = run_dir
        self.parent = parent
        self.clock = clock
        self.args_model = pydantic.create_model(
            f"DelegateTo{role_name.title().replace('_', '')}Args",
            __base__=DelegateArgs,
            input=(resolve_class(role.input), ...),
        )

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = Bus.open(self.run_dir / "bus.db", self.clock)
        active = bus.active_for(task_dir)
        if active:
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {active[0].status.value} as agent {active[0].agent}",
            )
        task_dir.mkdir(parents=True, exist_ok=True)
        spec = AgentSpec[type(args.input)](
            task_id=args.task_id,
            behaviour=self.role.behaviour,
            goal=args.goal,
            input=args.input,
            input_schema=self.role.input,
            answer_schema=self.role.answer,
            budget=self.role.budget,
        )
        (task_dir / "spec.json").write_text(spec.model_dump_json())
        task = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {task} for task {args.task_id} at {task_dir}")
```

`name`, `description` and `args_model` are assigned in `__init__` rather than declared on the class, because they vary per instance. `Tool` declares them, so Pyright still checks them.

- [ ] **Step 5: Write `delegate_tools`**

```python
# One delegate tool per declared role, so the role a parent picks is the tool it calls.
import collections.abc
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.contracts.role import Role
from ancalagon.tools.delegate.delegate_to import DelegateTo
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool


def delegate_tools(
    roles: collections.abc.Mapping[str, Role],
    run_dir: pathlib.Path,
    parent: int,
    clock: Clock,
) -> list[BoundTool]:
    return [
        bind_tool(DelegateTo(name, role, run_dir, parent, clock)) for name, role in roles.items()
    ]
```

- [ ] **Step 6: Delete what this replaces**

Delete `delegate.py`, `contract_pair.py`, `contract_source.py`, `allowance.py`, `within_parent.py`, `as_asked.py`. Then `grep -rn "ContractPair\|ContractSource\|Allowance\|WithinParent\|AsAsked\|input_json" ancalagon tests docs` and remove every remaining reference — a rename Pyright accepts can still leave string literals in fixtures. `Budget.slice` loses its only caller and goes too.

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_tools.py -k delegate_tool -v`
Expected: PASS

- [ ] **Step 8: Mutation-check**

Change `input=(resolve_class(role.input), ...)` to `input=(pydantic.BaseModel, ...)` and confirm both the `$defs["Query"]` assertion and the missing-`depth` rejection fail. Restore.

- [ ] **Step 9: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit
git add -A
git commit -m "A role is a tool: one delegate per declared role"
```

---

### Task 4: `spec.json` carries the role

**Files:**
- Modify: `ancalagon/contracts/agent_spec.py`, `ancalagon/contracts/task_spec.py`, `ancalagon/session.py:79,100,137-138`, `ancalagon/worker.py:62-105,118-122`, `ancalagon/tools/delegate/delegate_to.py`
- Test: `tests/unit/test_session.py`, `tests/unit/test_tools.py`

**Interfaces:**
- Consumes: `Role`, `delegate_tools`.
- Produces: `AgentSpec[InT](task_id: str, role: Role, goal: str, input: InT)`; `TaskSpec(task_id: str, role: Role, goal: str)`; `build_registry(config: Config, spec: TaskSpec, run_dir, parent, depth, output_class, clock) -> Registry`.

- [ ] **Step 1: Write the failing test**

Extend the existing session behaviour test so the spec it builds carries a role, and assert the two things that must follow from it:

```python
def test_a_session_takes_its_behaviour_and_budget_from_its_role():
    role = Role(behaviour="You investigate.", tools=("read_file",), budget=Budget(turns=2, tool_calls=4))
    spec = AgentSpec[FreeText](task_id="t", role=role, goal="find it", input=FreeText(text="go"))
    llm = FakeLLM([...])

    session = Session(spec=spec, input=FreeText(text="go"), ...)
    outcome = session.run()

    assert llm.seen[0].system.static.startswith("You investigate.")
    assert outcome.spent == Budget(turns=2, tool_calls=0)
```

Follow the existing `FakeLLM` construction in that file; do not invent a new fake.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_session.py -k role -v`
Expected: FAIL with `ValidationError: behaviour Field required`

- [ ] **Step 3: Shrink the specs**

```python
class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    role: Role
    goal: str
    input: InT
```

```python
class TaskSpec(pydantic.BaseModel, frozen=True):
    task_id: str
    role: Role
    goal: str
```

- [ ] **Step 4: Point `Session` at the role**

`session.py:79` becomes `self.remaining = spec.role.budget`, `:100` becomes `f"{self.spec.role.behaviour}\n\n"`, and `:137-138` read `self.spec.role.budget.turns` and `.tool_calls`.

- [ ] **Step 5: Build the registry from the spec's role**

`build_registry` takes `spec: TaskSpec` instead of `output_class`-plus-`budget`, and filters on the role's own tool list rather than the global one:

```python
    available: list[BoundTool] = [
        ...,
        *delegate_tools(config.roles, run_dir, parent, clock),
        bind_tool(CheckTask(run_dir=run_dir, clock=clock)),
        bind_tool(CollectTask(run_dir=run_dir, clock=clock)),
        bind_tool(AnswerTask(run_dir=run_dir, parent=parent, clock=clock)),
        bind_tool(NeedInput()),
        bind_tool(SubmitAnswer(output_class)),
    ]
    wanted = set(spec.role.tools)
    unknown = wanted - {t.name for t in available}
    if unknown:
        raise ValueError(
            f"role names unknown tools: {sorted(unknown)}; "
            f"available: {sorted(t.name for t in available)}"
        )
    permitted = [t for t in available if t.name in wanted]
    if depth >= config.max_depth:
        permitted = [t for t in permitted if not t.name.startswith("delegate_")]
    return Registry(permitted)
```

An empty `tools` list now means **no tools**, where the old global `enabled = []` meant *all* tools. That inversion is deliberate: a role states what it may use. `submit_answer` must therefore appear in every role's `tools`, or the final turn has nothing to force — decide this by running the suite and reading which tests break, and if a role without `submit_answer` is unusable, exempt it explicitly rather than silently.

- [ ] **Step 6: Simplify the worker's spec reading**

`worker.py:118-122` becomes:

```python
        spec = TaskSpec.model_validate_json(spec_text)
        output_class = resolve_class(spec.role.answer)
        input_class = resolve_class(spec.role.input)
        given = AgentSpec[input_class].model_validate_json(spec_text).input
```

- [ ] **Step 7: Simplify `DelegateTo.run`**

```python
        spec = AgentSpec[type(args.input)](
            task_id=args.task_id, role=self.role, goal=args.goal, input=args.input
        )
```

- [ ] **Step 8: Verify, mutation-check, commit**

Run the full unit suite. Then set `self.remaining = Budget(turns=99, tool_calls=99)` in `Session.__init__` and confirm the `outcome.spent` assertion fails. Restore.

```bash
git add -A
git commit -m "A spec carries its role, so nothing has to be told twice"
```

---

### Task 5: The root is a role

**Files:**
- Modify: `ancalagon/contracts/run_settings.py`, `ancalagon/cli.py:54-93,105-123,156-168`, `ancalagon/config/load.py:23-29`
- Test: `tests/unit/test_cli_settings.py`, `tests/integration/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `RunSettings(run_dir: str, goal_file: str, input_file: str, role: str)`; `root_spec(config: Config) -> AgentSpec[pydantic.BaseModel]`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_root_spec_comes_from_its_role_and_its_two_files(tmp_path: pathlib.Path):
    shapes = tmp_path / "shapes.py"
    shapes.write_text("import pydantic\n\n\nclass Query(pydantic.BaseModel):\n    area: str\n")
    (tmp_path / "goal.md").write_text("map it")
    (tmp_path / "input.json").write_text('{"area": "bus"}')
    role = Role(
        behaviour="Analyse.",
        input=ClassRef(module=str(shapes), name="Query"),
        tools=("read_file", "submit_answer"),
        budget=Budget(turns=3, tool_calls=6),
    )
    config = Config(..., roles={"analyst": role},
                    run=RunSettings(goal_file=str(tmp_path / "goal.md"),
                                    input_file=str(tmp_path / "input.json"), role="analyst"))

    spec = root_spec(config)

    assert spec.task_id == "root"
    assert spec.role == role
    assert spec.goal == "map it"
    assert spec.input.model_dump() == {"area": "bus"}

    absent = config.model_copy(update={"run": config.run.model_copy(update={"role": "nobody"})})
    with pytest.raises(ValueError, match="no role named nobody"):
        root_spec(absent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_cli_settings.py -k root_spec -v`
Expected: FAIL with `ImportError: cannot import name 'root_spec'`

- [ ] **Step 3: Change `RunSettings`**

```python
# What one run varies from every other: where it lives, what it is asked, and as which role.
import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    run_dir: str = ""
    goal_file: str = ""
    input_file: str = ""
    role: str = ""
```

The `contract_module`/`contract_class` validator goes with the fields it guarded.

- [ ] **Step 4: Write `root_spec` in `cli.py`, deleting three functions**

```python
def root_spec(config: Config) -> AgentSpec[pydantic.BaseModel]:
    if config.run.role not in config.roles:
        raise ValueError(f"[run] role: no role named {config.run.role}; "
                         f"declared: {sorted(config.roles)}")
    role = config.roles[config.run.role]
    goal = goal_of(config.run)
    input_class = resolve_class(role.input)
    given = (
        input_class.model_validate_json(_text_of(pathlib.Path(config.run.input_file), "input_file"))
        if config.run.input_file
        else input_class.model_validate({"text": goal})
    )
    return AgentSpec[input_class](task_id="root", role=role, goal=goal, input=given)
```

Delete `answer_schema_of`, `contract_source`, `_class_names` and `install_contracts`. `main` loses its contract writes and becomes `(task_dir / "spec.json").write_text(root_spec(config).model_dump_json())`.

The `else` branch validates `{"text": goal}` against whatever the role's input class is, so a role with a structured input and no `input_file` fails at startup with Pydantic naming the missing fields — which is the intended behaviour, not an accident.

- [ ] **Step 5: Update `load.py` and every config fixture**

`_run_settings` reads `run["input_file"]` and `run["role"]` and no longer reads `contract_module`/`contract_class`. Every TOML fixture in `tests/` gains `[roles.*]` and a `[run] role`; the integration harness's `_config` gains a `role` parameter defaulting to a prose role it declares.

- [ ] **Step 6: Verify, mutation-check, commit**

Run both suites. Then make `root_spec` ignore `input_file` and always build from the goal, and confirm the `spec.input` assertion fails. Restore.

```bash
git add -A
git commit -m "The root is a role like any other, with its own two files"
```

---

### Task 6: Documentation and the example config

**Files:**
- Modify: `README.md:19-45`, `docs/architecture.md:36-46,106-115`, `ancalagon.example.toml`
- Test: none — documentation.

- [ ] **Step 1: Rewrite `ancalagon.example.toml`**

Remove `[agent]`, `[tools]`, `[budget]`, and `[run] contract_module`/`contract_class`. Add two roles — one prose, one with a declared contract — and `[run] role`, `[run] input_file`. `[budget]` goes because a budget now belongs to a role; check whether `Config.budget` still has a caller after Task 4 and delete the field if it does not.

- [ ] **Step 2: Rewrite the README's Running section**

It currently describes `contract_module`/`contract_class` and a single global budget. It must describe declaring roles, naming one in `[run] role`, and the two input files.

- [ ] **Step 3: Correct `docs/architecture.md`**

Step 3 of the CLI walkthrough (`:36-46`) describes writing contract modules into the task directory — that no longer happens at all. The tools section must say that delegate tools are per-role and built at startup.

- [ ] **Step 4: Grep for stale text**

```bash
grep -rn "contract_module\|contract_class\|root_behaviour\|input_json\|\[tools\]" README.md docs/ ancalagon.example.toml
```

Expected: no matches outside `docs/superpowers/specs/`, which is immutable.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Document roles, and stop documenting the contracts nobody writes now"
```

---

## Self-Review

**Spec coverage.** Role definition and `[roles.*]` → Tasks 1–2. Nothing built in, `FreeText` as the absent default → Task 1 Step 3, Task 2 Step 1. `tools` per role naming `delegate_<role>` → Task 4 Step 5. Budget authoritative, `Allowance` deleted → Tasks 3–4. One delegate tool per role with a concrete schema → Task 3. `input_json` gone → Task 3 Step 3. Root as a role with `input_file` → Task 5. Role embedded in `spec.json` → Task 4. Contract modules not copied → Task 1 (`resolve_class` loses `base`), Task 5 (`install_contracts` deleted). Docs → Task 6.

**Two things this plan leaves for the implementer to settle, deliberately flagged rather than guessed:**

1. Whether `submit_answer` must appear in every role's `tools` (Task 4 Step 5). An empty list now means no tools, inverting the old global default, and the final turn forces `submit_answer`. The suite will show whether a role omitting it is unusable.
2. Whether `Config.budget` survives Task 4 (Task 6 Step 1). If every budget comes from a role, the global one has no caller and should be deleted.

**Type consistency.** `Role`, `ClassRef`, `resolve_class(ref)`, `delegate_tools(roles, run_dir, parent, clock)`, `AgentSpec[InT](task_id, role, goal, input)`, `TaskSpec(task_id, role, goal)`, `RunSettings(run_dir, goal_file, input_file, role)`, `root_spec(config)` are used identically in every task that mentions them.
