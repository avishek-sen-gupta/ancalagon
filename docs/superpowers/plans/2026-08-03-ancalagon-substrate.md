# Ancalagon Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the agent substrate — a multi-turn agent that uses tools, delegates work to isolated subagent processes under a supervisor, and records everything to SQLite rows and files.

**Architecture:** Three process kinds sharing no memory. A parent enqueues a task row and writes `spec.json`; a supervisor claims the row, spawns `python -m ancalagon.worker`, reaps it, and writes status back; the worker runs one `Session` and writes `outcome.json` plus `transcript.jsonl`. There is no IPC — communication is rows and files. `Popen` appears in exactly one module.

**Tech Stack:** Python 3.13, uv, Pydantic v2, LiteLLM, SQLite (stdlib), pytest, Black, Pyright strict.

**Source spec:** `docs/superpowers/specs/2026-08-02-ancalagon-agent-harness-design.md`

**Out of scope (Plan B):** `run_harness`, generated traversals, codegen prompting.

## Global Constraints

Copied verbatim from `CLAUDE.md` and the spec. Every task's requirements implicitly include this section.

- **No gold plating.** Build what the task asks for and nothing more. No abstraction layers, extension points, or configuration knobs no current caller needs.
- **No comments.** The only permitted comment is a one-line header on a class or module stating its purpose. No docstrings on functions, no inline explanations, no section dividers, no TODOs.
- **Few tests, each covering a whole behaviour.** One test function per behaviour, asserting everything that behaviour implies. Do not split into one test per assertion.
- **No `Any`, no `object`, no JSON-blob types** (`JsonValue`, `JsonDict`, `JsonObject`, `JsonType`, `AnyJson`). JSON exists only as text in files and strings; `model_validate_json` turns it into a concrete model at the boundary.
- **No bare collection types.** `dict[str, int]` not `dict`; `list[Node]` not `list`. Pyright strict enforces via `reportMissingTypeArgument`.
- **No `None`.** No `None` defaults, no `None` returns from non-`None` signatures, no defensive `None` checks. Use empty structures and the null object pattern.
- **Dataclasses are `frozen=True`.** Pydantic models that are values use `frozen=True`.
- **Fully qualified imports.** No relative imports. Import from the owning module: `from ancalagon.contracts.budget import Budget`. Package `__init__.py` files stay empty — never re-export, so `from ancalagon.contracts import Budget` will not work and must not be made to.
- **Task code blocks predate the file split.** Their logic is authoritative; their import lines are not. Rewrite every import to the split module path from the File structure section. This applies to test files too.
- **One class per file, strictly.** Every class — including enums, exception types, Protocols, and Pydantic argument models — gets its own module named after it in `snake_case`. A module may contain module-level functions and type aliases alongside its single class, or consist only of functions. Where the plan's task text shows several classes in one code block, that block is the *content*; distribute it across the exact files named in that task's **Files** list. The code itself is unchanged.
- **Shared helpers live once.** `schema_of(name, description, model)` lives in `ancalagon/llm/schema_of.py` and is imported by every tool. Do not copy it into each tool module.
- **Functional core, imperative shell.** Mutation only in the shell (file writes, subprocess, SQLite, LLM calls).
- **Logging, not `print`.**
- **Enums, not raw strings**, for fixed value sets.
- Every command is prefixed `uv run`.
- Python floor: **3.13**.
- LoC ceiling for the whole project: **~1100** excluding tests and SQL.

## File structure

One class per module, named after the class in `snake_case`. Modules holding only functions or type aliases are named for what they do.

```
pyproject.toml

ancalagon/contracts/role.py               Role
ancalagon/contracts/block_kind.py         BlockKind
ancalagon/contracts/outcome_kind.py       OutcomeKind
ancalagon/contracts/text.py               Text
ancalagon/contracts/tool_use.py           ToolUse
ancalagon/contracts/tool_result_block.py  ToolResultBlock
ancalagon/contracts/block.py              Block alias
ancalagon/contracts/message.py            Message
ancalagon/contracts/reply.py              Reply
ancalagon/contracts/budget.py             Budget
ancalagon/contracts/tool_result.py        ToolResult
ancalagon/contracts/agent_spec.py         AgentSpec, InT
ancalagon/contracts/completed.py          Completed, OutT
ancalagon/contracts/exhausted.py          Exhausted
ancalagon/contracts/needs_input.py        NeedsInput
ancalagon/contracts/failed.py             Failed
ancalagon/contracts/timed_out.py          TimedOut
ancalagon/contracts/outcome.py            Outcome alias, outcome_adapter
ancalagon/contracts/free_text.py          FreeText
ancalagon/contracts/resolve.py            resolve_output_class

ancalagon/config/config.py                Config
ancalagon/config/load.py                  load_config

ancalagon/workspace/scope_error.py        ScopeError
ancalagon/workspace/workspace.py          Workspace

ancalagon/migrations.py                   user_version, latest_version, migrate

ancalagon/bus/task_status.py              TaskStatus
ancalagon/bus/task_row.py                 TaskRow
ancalagon/bus/message_row.py              MessageRow
ancalagon/bus/bus.py                      Bus

ancalagon/llm/tool_schema.py              ToolSchema
ancalagon/llm/schema_of.py                schema_of
ancalagon/llm/llm.py                      LLM protocol
ancalagon/llm/fake_llm.py                 FakeLLM
ancalagon/llm/litellm_client.py           LiteLLMClient

ancalagon/transcript/transcript.py        Transcript
ancalagon/transcript/history.py           load, repair, INTERRUPTED

ancalagon/tools/registry/tool_context.py  ToolContext
ancalagon/tools/registry/tool.py          Tool protocol
ancalagon/tools/registry/registry.py      Registry

ancalagon/tools/files/path_args.py        PathArgs
ancalagon/tools/files/write_args.py       WriteArgs
ancalagon/tools/files/edit_args.py        EditArgs
ancalagon/tools/files/read_file.py        ReadFile
ancalagon/tools/files/write_file.py       WriteFile
ancalagon/tools/files/edit_file.py        EditFile
ancalagon/tools/files/delete_file.py      DeleteFile
ancalagon/tools/files/list_dir.py         ListDir

ancalagon/tools/search/grep_args.py       GrepArgs
ancalagon/tools/search/sed_args.py        SedArgs
ancalagon/tools/search/run_command.py     run_command
ancalagon/tools/search/ripgrep.py         Ripgrep
ancalagon/tools/search/ast_grep.py        AstGrep
ancalagon/tools/search/sed.py             Sed

ancalagon/tools/parse/parse_args.py       ParseArgs
ancalagon/tools/parse/tree_sitter_tool.py TreeSitter, LANGUAGES

ancalagon/tools/delegate/delegate_args.py DelegateArgs
ancalagon/tools/delegate/task_args.py     TaskArgs
ancalagon/tools/delegate/delegate.py      Delegate
ancalagon/tools/delegate/check_task.py    CheckTask
ancalagon/tools/delegate/collect_task.py  CollectTask

ancalagon/session.py                      Session
ancalagon/supervisor/process.py           Process protocol
ancalagon/supervisor/spawner.py           Spawner protocol
ancalagon/supervisor/clock.py             Clock protocol
ancalagon/supervisor/system_clock.py      SystemClock
ancalagon/supervisor/subprocess_spawner.py SubprocessSpawner
ancalagon/supervisor/supervisor.py        Supervisor
ancalagon/worker.py                       main, cli, build_registry
ancalagon/cli.py                          main, cli
```

Every package directory needs an `__init__.py`. Leave them empty — imports are fully qualified, so no re-exports.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/unit/test_scaffold.py`, and an empty `__init__.py` in each of: `ancalagon/`, `ancalagon/contracts/`, `ancalagon/config/`, `ancalagon/workspace/`, `ancalagon/bus/`, `ancalagon/llm/`, `ancalagon/transcript/`, `ancalagon/supervisor/`, `ancalagon/tools/`, `ancalagon/tools/registry/`, `ancalagon/tools/files/`, `ancalagon/tools/search/`, `ancalagon/tools/parse/`, `ancalagon/tools/delegate/`

**Interfaces:**
- Consumes: nothing
- Produces: a working `uv` project where `uv run pytest`, `uv run black .`, and `uv run pyright` all succeed. All later tasks depend on this.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "ancalagon"
version = "0.1.0"
description = "Agent harness for reverse engineering"
requires-python = ">=3.13"
dependencies = [
    "pydantic>=2.12",
    "litellm>=1.60",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "black>=24.0",
    "pyright>=1.1.409",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["ancalagon"]

[tool.black]
line-length = 100
target-version = ["py313"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty package files**

```bash
mkdir -p ancalagon/tools tests/unit tests/integration
touch ancalagon/__init__.py ancalagon/tools/__init__.py
touch tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 3: Write the failing test**

Create `tests/unit/test_scaffold.py`:

```python
import ancalagon


def test_package_imports_and_migrations_are_present():
    root = pathlib.Path(ancalagon.__file__).parent
    assert (root / "migrations" / "001_init.up.sql").exists()
    assert (root / "migrations" / "001_init.down.sql").exists()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_scaffold.py -v`
Expected: FAIL with `NameError: name 'pathlib' is not defined`

- [ ] **Step 5: Add the missing import**

Add `import pathlib` as the first line of `tests/unit/test_scaffold.py`.

- [ ] **Step 6: Run all gates**

```bash
uv sync
uv run pytest tests/unit -v
uv run black --check .
uv run pyright
```
Expected: pytest PASS, black clean, pyright zero errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock ancalagon tests
git commit -m "Scaffold uv project with pytest, Black and Pyright strict"
```

---

### Task 2: Contracts

**Files:**
- Create, one class each, per the File structure section: `ancalagon/contracts/role.py`, `block_kind.py`, `outcome_kind.py`, `text.py`, `tool_use.py`, `tool_result_block.py`, `block.py`, `message.py`, `reply.py`, `budget.py`, `tool_result.py`, `agent_spec.py`, `completed.py`, `exhausted.py`, `needs_input.py`, `failed.py`, `timed_out.py`, `outcome.py`, `free_text.py`, `resolve.py`
- Test: `tests/unit/test_contracts.py`

`agent_spec.py` declares `InT`; `completed.py` declares `OutT`; `exhausted.py` imports `OutT` from `completed.py`. `block.py` holds only the `Block` union alias; `outcome.py` holds the `Outcome` alias and `outcome_adapter`.

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Role(StrEnum)`: `USER`, `ASSISTANT`
  - `BlockKind(StrEnum)`: `TEXT`, `TOOL_USE`, `TOOL_RESULT`
  - `Text(kind, text: str)`, `ToolUse(kind, id: str, name: str, arguments: str)`, `ToolResultBlock(kind, tool_use_id: str, content: str, is_error: bool)`
  - `Block = Text | ToolUse | ToolResultBlock`
  - `Message(role: Role, blocks: list[Block], agent: int, seq: int, ts: str)`
  - `Budget(turns: int, tool_calls: int)` frozen, with `spend_turn()`, `spend_tool_call()`, `slice(turns, tool_calls)`, `turns_exhausted`, `tool_calls_exhausted`
  - `ToolResult(ok, summary, path, byte_count, truncated, error)`
  - `AgentSpec[InT](task_id, behaviour, goal, input, output, budget, tools)`
  - `Completed[OutT]`, `Exhausted[OutT]`, `NeedsInput`, `Failed`, `TimedOut`, `Outcome`
  - `Reply(blocks: list[Block], stop_reason: str)`
  - `FreeText(text: str)`
  - `resolve_output_class(output: str, base: pathlib.Path) -> type[pydantic.BaseModel]`
  - `outcome_adapter(cls: type[pydantic.BaseModel]) -> pydantic.TypeAdapter[Outcome]`

`ToolUse.arguments` is a **JSON string**, not a parsed structure. This is what keeps the codebase free of JSON-blob types: raw tool arguments stay text until a tool validates them into its own model.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_contracts.py`:

```python
import pathlib

import pydantic
import pytest

from ancalagon.contracts import (
    AgentSpec,
    Budget,
    Completed,
    Failed,
    FreeText,
    Message,
    Role,
    Text,
    ToolUse,
    outcome_adapter,
    resolve_output_class,
)


class NodeSummary(pydantic.BaseModel):
    text: str
    confidence: int


def test_contracts_round_trip_and_budget_arithmetic(tmp_path: pathlib.Path):
    budget = Budget(turns=3, tool_calls=10)
    assert budget.spend_turn() == Budget(turns=2, tool_calls=10)
    assert budget.spend_tool_call() == Budget(turns=3, tool_calls=9)
    assert budget.slice(turns=1, tool_calls=4) == Budget(turns=1, tool_calls=4)
    assert Budget(turns=0, tool_calls=5).turns_exhausted is True
    assert Budget(turns=1, tool_calls=0).tool_calls_exhausted is True
    with pytest.raises(ValueError):
        budget.slice(turns=99, tool_calls=1)

    spec = AgentSpec[NodeSummary](
        task_id="node_7",
        behaviour="You summarise.",
        goal="Summarise this node.",
        input=NodeSummary(text="body", confidence=1),
        output="contracts.py:NodeSummary",
        budget=budget,
    )
    assert spec.tools == []
    assert AgentSpec[NodeSummary].model_validate_json(spec.model_dump_json()) == spec

    message = Message(
        role=Role.ASSISTANT,
        blocks=[Text(text="hi"), ToolUse(id="tu_1", name="ripgrep", arguments='{"pattern":"x"}')],
        agent=17,
        seq=0,
        ts="2026-08-03T00:00:00Z",
    )
    restored = Message.model_validate_json(message.model_dump_json())
    assert restored == message
    assert isinstance(restored.blocks[1], ToolUse)
    assert restored.blocks[1].arguments == '{"pattern":"x"}'

    adapter = outcome_adapter(NodeSummary)
    completed = Completed[NodeSummary](
        value=NodeSummary(text="done", confidence=2),
        summary="finished",
        spent=Budget(turns=1, tool_calls=2),
    )
    assert adapter.validate_json(completed.model_dump_json()) == completed
    failed = Failed(error="boom", summary="died", spent=Budget(turns=0, tool_calls=0))
    assert adapter.validate_json(failed.model_dump_json()) == failed

    module = tmp_path / "contracts.py"
    module.write_text(
        "import pydantic\n\n\nclass Verdict(pydantic.BaseModel):\n    ok: bool\n"
    )
    resolved = resolve_output_class("contracts.py:Verdict", tmp_path)
    assert resolved.__name__ == "Verdict"
    assert resolved.model_validate_json('{"ok": true}').ok is True

    assert FreeText(text="plain").text == "plain"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.contracts'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/contracts.py`:

```python
import enum
import importlib.util
import pathlib
import sys
import typing

import pydantic

InT = typing.TypeVar("InT", bound=pydantic.BaseModel)
OutT = typing.TypeVar("OutT", bound=pydantic.BaseModel)


class Role(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class BlockKind(enum.StrEnum):
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


class OutcomeKind(enum.StrEnum):
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class Text(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TEXT] = BlockKind.TEXT
    text: str


class ToolUse(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TOOL_USE] = BlockKind.TOOL_USE
    id: str
    name: str
    arguments: str


class ToolResultBlock(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TOOL_RESULT] = BlockKind.TOOL_RESULT
    tool_use_id: str
    content: str
    is_error: bool = False


Block = Text | ToolUse | ToolResultBlock


class Message(pydantic.BaseModel, frozen=True):
    role: Role
    blocks: list[Block]
    agent: int
    seq: int
    ts: str


class Reply(pydantic.BaseModel, frozen=True):
    blocks: list[Block]
    stop_reason: str


class Budget(pydantic.BaseModel, frozen=True):
    turns: int
    tool_calls: int

    @property
    def turns_exhausted(self) -> bool:
        return self.turns <= 0

    @property
    def tool_calls_exhausted(self) -> bool:
        return self.tool_calls <= 0

    def spend_turn(self) -> "Budget":
        return Budget(turns=self.turns - 1, tool_calls=self.tool_calls)

    def spend_tool_call(self) -> "Budget":
        return Budget(turns=self.turns, tool_calls=self.tool_calls - 1)

    def slice(self, turns: int, tool_calls: int) -> "Budget":
        if turns > self.turns or tool_calls > self.tool_calls:
            raise ValueError(f"cannot slice {turns}/{tool_calls} from {self.turns}/{self.tool_calls}")
        return Budget(turns=turns, tool_calls=tool_calls)


class ToolResult(pydantic.BaseModel, frozen=True):
    ok: bool
    summary: str
    path: pathlib.Path
    byte_count: int = 0
    truncated: bool = False
    error: str = ""


class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input: InT
    output: str
    budget: Budget
    tools: list[str] = []


class Completed(pydantic.BaseModel, typing.Generic[OutT], frozen=True):
    kind: typing.Literal[OutcomeKind.COMPLETED] = OutcomeKind.COMPLETED
    value: OutT
    summary: str
    spent: Budget


class Exhausted(pydantic.BaseModel, typing.Generic[OutT], frozen=True):
    kind: typing.Literal[OutcomeKind.EXHAUSTED] = OutcomeKind.EXHAUSTED
    value: OutT
    summary: str
    spent: Budget


class NeedsInput(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.NEEDS_INPUT] = OutcomeKind.NEEDS_INPUT
    question: str
    summary: str
    spent: Budget


class Failed(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.FAILED] = OutcomeKind.FAILED
    error: str
    summary: str
    spent: Budget


class TimedOut(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.TIMED_OUT] = OutcomeKind.TIMED_OUT
    summary: str
    spent: Budget


Outcome = (
    Completed[pydantic.BaseModel]
    | Exhausted[pydantic.BaseModel]
    | NeedsInput
    | Failed
    | TimedOut
)


class FreeText(pydantic.BaseModel, frozen=True):
    text: str


def outcome_adapter(cls: type[pydantic.BaseModel]) -> pydantic.TypeAdapter[Outcome]:
    return pydantic.TypeAdapter(
        Completed[cls] | Exhausted[cls] | NeedsInput | Failed | TimedOut
    )


def resolve_output_class(output: str, base: pathlib.Path) -> type[pydantic.BaseModel]:
    filename, _, class_name = output.partition(":")
    path = base / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    resolved = getattr(module, class_name)
    if not issubclass(resolved, pydantic.BaseModel):
        raise TypeError(f"{output} is not a pydantic model")
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Run gates**

```bash
uv run black . && uv run pyright && uv run precommit-scripts/check-type-hygiene
```
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add ancalagon/contracts.py tests/unit/test_contracts.py
git commit -m "Add boundary contracts with generic AgentSpec and Outcome union"
```

---

### Task 3: Config and workspace scoping

**Files:**
- Create: `ancalagon/config/config.py` (`Config`), `ancalagon/config/load.py` (`load_config`), `ancalagon/workspace/scope_error.py` (`ScopeError`), `ancalagon/workspace/workspace.py` (`Workspace`)
- Test: `tests/unit/test_workspace_scoping.py`

**Interfaces:**
- Consumes: `ancalagon.contracts.Budget`
- Produces:
  - `Config(write_root, read_roots, model, max_tokens, budget, max_concurrent_agents, agent_timeout_s, max_depth, tools, summary_chars)`
  - `load_config(path: pathlib.Path) -> Config`
  - `ScopeError(Exception)`
  - `Workspace(write_root, read_roots)` with `resolve_read(p) -> pathlib.Path`, `resolve_write(p) -> pathlib.Path`
  - `Workspace.from_config(config) -> Workspace`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_workspace_scoping.py`:

```python
import pathlib

import pytest

from ancalagon.config import load_config
from ancalagon.workspace import ScopeError, Workspace


def test_scoping_rejects_every_escape_and_config_round_trips(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    read_only = tmp_path / "artifacts"
    outside = tmp_path / "elsewhere"
    for d in (write_root, read_only, outside):
        d.mkdir()
    (read_only / "a.txt").write_text("data")
    (outside / "secret.txt").write_text("nope")

    ws = Workspace(write_root=write_root, read_roots=(read_only, write_root))

    assert ws.resolve_write(write_root / "out.json") == (write_root / "out.json").resolve()
    assert ws.resolve_read(read_only / "a.txt") == (read_only / "a.txt").resolve()
    assert ws.resolve_read(write_root / "out.json") == (write_root / "out.json").resolve()

    with pytest.raises(ScopeError):
        ws.resolve_write(read_only / "a.txt")
    with pytest.raises(ScopeError):
        ws.resolve_read(outside / "secret.txt")
    with pytest.raises(ScopeError):
        ws.resolve_write(write_root / ".." / "elsewhere" / "x.txt")

    link = write_root / "escape"
    link.symlink_to(outside)
    with pytest.raises(ScopeError):
        ws.resolve_write(link / "secret.txt")

    config_path = tmp_path / "ancalagon.toml"
    config_path.write_text(
        f'''
[workspace]
write_root = "{write_root}"
read_roots = ["{read_only}"]

[model]
name = "claude-opus-5"
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 1
agent_timeout_s = 3600
max_depth = 1
summary_chars = 1000

[tools]
enabled = ["read_file", "ripgrep"]
'''
    )
    config = load_config(config_path)
    assert config.write_root == write_root
    assert config.read_roots == (read_only,)
    assert config.model == "claude-opus-5"
    assert config.budget.turns == 20
    assert config.max_concurrent_agents == 1
    assert config.agent_timeout_s == 3600
    assert config.tools == ["read_file", "ripgrep"]
    assert Workspace.from_config(config).resolve_read(read_only / "a.txt").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_workspace_scoping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.config'`

- [ ] **Step 3: Write `ancalagon/workspace.py`**

```python
import pathlib

import ancalagon.config


class ScopeError(Exception):
    pass


class Workspace:
    def __init__(self, write_root: pathlib.Path, read_roots: tuple[pathlib.Path, ...]):
        self.write_root = write_root.resolve()
        self.read_roots = tuple(r.resolve() for r in read_roots)

    @classmethod
    def from_config(cls, config: "ancalagon.config.Config") -> "Workspace":
        return cls(write_root=config.write_root, read_roots=(*config.read_roots, config.write_root))

    def resolve_write(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.write_root):
            raise ScopeError(f"{path} is outside write_root {self.write_root}")
        return resolved

    def resolve_read(self, path: pathlib.Path) -> pathlib.Path:
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in self.read_roots):
            raise ScopeError(f"{path} is outside read_roots {self.read_roots}")
        return resolved
```

- [ ] **Step 4: Write `ancalagon/config.py`**

```python
import pathlib
import tomllib

import pydantic

import ancalagon.contracts


class Config(pydantic.BaseModel, frozen=True):
    write_root: pathlib.Path
    read_roots: tuple[pathlib.Path, ...]
    model: str
    max_tokens: int
    budget: ancalagon.contracts.Budget
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    tools: list[str]
    summary_chars: int


def load_config(path: pathlib.Path) -> Config:
    raw = tomllib.loads(path.read_text())
    workspace = raw["workspace"]
    model = raw["model"]
    budget = raw["budget"]
    limits = raw["limits"]
    return Config(
        write_root=pathlib.Path(workspace["write_root"]),
        read_roots=tuple(pathlib.Path(p) for p in workspace["read_roots"]),
        model=model["name"],
        max_tokens=model["max_tokens"],
        budget=ancalagon.contracts.Budget(turns=budget["turns"], tool_calls=budget["tool_calls"]),
        max_concurrent_agents=limits["max_concurrent_agents"],
        agent_timeout_s=limits["agent_timeout_s"],
        max_depth=limits["max_depth"],
        tools=raw["tools"]["enabled"],
        summary_chars=limits["summary_chars"],
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_workspace_scoping.py -v`
Expected: PASS. If the symlink assertion fails, the cause is `resolve()` not being called before the containment check — fix the implementation, not the test.

- [ ] **Step 6: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/config.py ancalagon/workspace.py tests/unit/test_workspace_scoping.py
git commit -m "Add TOML config and read/write scope enforcement"
```

---

### Task 4: Migration runner

**Files:**
- Create: `ancalagon/migrations.py`
- Test: `tests/unit/test_migrations.py`
- Existing: `ancalagon/migrations/001_init.up.sql`, `ancalagon/migrations/001_init.down.sql` (already committed)

**Interfaces:**
- Consumes: nothing
- Produces: `user_version(conn) -> int`, `latest_version() -> int`, `migrate(conn, target) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migrations.py`:

```python
import pathlib
import sqlite3

import pytest

from ancalagon.migrations import latest_version, migrate, user_version


def test_migrations_round_trip_and_checks_reject_bad_rows(tmp_path: pathlib.Path):
    conn = sqlite3.connect(tmp_path / "bus.db")

    assert user_version(conn) == 0
    assert latest_version() == 1

    migrate(conn, latest_version())
    assert user_version(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tasks", "messages", "cursors"} <= tables

    conn.execute("INSERT INTO tasks (dir, status) VALUES ('ws/tasks/a', 'queued')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tasks (dir, status) VALUES ('ws/tasks/b', 'bogus')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tasks (dir, status, summary) VALUES ('ws/tasks/c', 'queued', ?)",
            ("x" * 1001,),
        )

    migrate(conn, 0)
    assert user_version(conn) == 0
    remaining = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "tasks" not in remaining
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_migrations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.migrations'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/migrations.py`:

```python
import pathlib
import sqlite3

DIRECTORY = pathlib.Path(__file__).parent / "migrations"


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version() -> int:
    return max(int(p.name.split("_", 1)[0]) for p in DIRECTORY.glob("*.up.sql"))


def _script(version: int, direction: str) -> pathlib.Path:
    matches = sorted(DIRECTORY.glob(f"{version:03d}_*.{direction}.sql"))
    if not matches:
        raise FileNotFoundError(f"no {direction} migration for version {version}")
    return matches[0]


def migrate(conn: sqlite3.Connection, target: int) -> None:
    current = user_version(conn)
    if target > current:
        versions = range(current + 1, target + 1)
        direction = "up"
    else:
        versions = range(current, target, -1)
        direction = "down"
    for version in versions:
        conn.executescript(_script(version, direction).read_text())
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/migrations.py tests/unit/test_migrations.py
git commit -m "Add PRAGMA user_version migration runner"
```

---

### Task 5: The bus

**Files:**
- Create: `ancalagon/bus/task_status.py` (`TaskStatus`), `ancalagon/bus/task_row.py` (`TaskRow`), `ancalagon/bus/message_row.py` (`MessageRow`), `ancalagon/bus/bus.py` (`Bus`, and the module-private `_now`)
- Test: `tests/unit/test_bus.py`

**Interfaces:**
- Consumes: `ancalagon.migrations.migrate`, `ancalagon.migrations.latest_version`
- Produces:
  - `TaskStatus(StrEnum)`: `QUEUED`, `RUNNING`, `COMPLETED`, `CRASHED`, `TIMEOUT`, `ABANDONED`
  - `TaskRow(id, dir, parent, status, pid, exit_code, summary, started, finished)`
  - `MessageRow(id, ts, sender, addressee, kind, summary, ref_path)`
  - `Bus.open(path) -> Bus`
  - `Bus.enqueue(dir: pathlib.Path, parent: int) -> int`
  - `Bus.claim(limit: int) -> list[TaskRow]`
  - `Bus.mark_running(task_id: int, pid: int) -> None`
  - `Bus.finish(task_id: int, status: TaskStatus, exit_code: int, summary: str) -> None`
  - `Bus.get(task_id: int) -> TaskRow`
  - `Bus.running() -> list[TaskRow]`
  - `Bus.post(sender: int, addressee: int, kind: str, summary: str, ref_path: str) -> None`
  - `Bus.inbox(consumer: int) -> list[MessageRow]`

`claim` must be atomic: two consumers racing must never receive the same row. Achieve this with a single `UPDATE ... WHERE id IN (SELECT ... WHERE status='queued' LIMIT n) RETURNING *` inside an `IMMEDIATE` transaction.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bus.py`:

```python
import pathlib

from ancalagon.bus import Bus, TaskStatus


def test_bus_enqueues_claims_once_and_advances_cursor(tmp_path: pathlib.Path):
    db = tmp_path / "bus.db"
    bus = Bus.open(db)
    other = Bus.open(db)

    first = bus.enqueue(pathlib.Path("ws/tasks/a"), parent=0)
    second = bus.enqueue(pathlib.Path("ws/tasks/b"), parent=first)
    assert bus.get(first).status is TaskStatus.QUEUED
    assert bus.get(second).parent == first

    claimed = bus.claim(limit=10)
    assert sorted(t.id for t in claimed) == [first, second]
    assert other.claim(limit=10) == []

    bus.mark_running(first, pid=4242)
    assert bus.get(first).pid == 4242
    assert [t.id for t in bus.running()] == [first]

    bus.finish(first, TaskStatus.COMPLETED, exit_code=0, summary="done")
    finished = bus.get(first)
    assert finished.status is TaskStatus.COMPLETED
    assert finished.summary == "done"
    assert finished.finished != ""
    assert bus.running() == []

    bus.post(sender=first, addressee=0, kind="task_done", summary="done", ref_path="ws/tasks/a")
    inbox = bus.inbox(consumer=0)
    assert [m.kind for m in inbox] == ["task_done"]
    assert inbox[0].sender == first
    assert bus.inbox(consumer=0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.bus'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/bus.py`:

```python
import datetime
import enum
import pathlib
import sqlite3

import pydantic

import ancalagon.migrations


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CRASHED = "crashed"
    TIMEOUT = "timeout"
    ABANDONED = "abandoned"


class TaskRow(pydantic.BaseModel, frozen=True):
    id: int
    dir: str
    parent: int
    status: TaskStatus
    pid: int
    exit_code: int
    summary: str
    started: str
    finished: str


class MessageRow(pydantic.BaseModel, frozen=True):
    id: int
    ts: str
    sender: int
    addressee: int
    kind: str
    summary: str
    ref_path: str


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


class Bus:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @classmethod
    def open(cls, path: pathlib.Path) -> "Bus":
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        ancalagon.migrations.migrate(conn, ancalagon.migrations.latest_version())
        return cls(conn)

    def enqueue(self, dir: pathlib.Path, parent: int) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tasks (dir, parent, status, started) VALUES (?, ?, ?, ?) RETURNING id",
            (str(dir), parent, TaskStatus.QUEUED.value, ""),
        )
        return int(cursor.fetchone()["id"])

    def claim(self, limit: int) -> list[TaskRow]:
        self.conn.execute("BEGIN IMMEDIATE")
        rows = self.conn.execute(
            "UPDATE tasks SET status = ?, started = ? WHERE id IN "
            "(SELECT id FROM tasks WHERE status = ? ORDER BY id LIMIT ?) RETURNING *",
            (TaskStatus.RUNNING.value, _now(), TaskStatus.QUEUED.value, limit),
        ).fetchall()
        self.conn.execute("COMMIT")
        return [TaskRow.model_validate(dict(r)) for r in rows]

    def mark_running(self, task_id: int, pid: int) -> None:
        self.conn.execute("UPDATE tasks SET pid = ? WHERE id = ?", (pid, task_id))

    def finish(self, task_id: int, status: TaskStatus, exit_code: int, summary: str) -> None:
        self.conn.execute(
            "UPDATE tasks SET status = ?, exit_code = ?, summary = ?, finished = ? WHERE id = ?",
            (status.value, exit_code, summary, _now(), task_id),
        )

    def get(self, task_id: int) -> TaskRow:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"no task {task_id}")
        return TaskRow.model_validate(dict(row))

    def running(self) -> list[TaskRow]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY id", (TaskStatus.RUNNING.value,)
        ).fetchall()
        return [TaskRow.model_validate(dict(r)) for r in rows]

    def post(self, sender: int, addressee: int, kind: str, summary: str, ref_path: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (ts, sender, addressee, kind, summary, ref_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), sender, addressee, kind, summary, ref_path),
        )

    def inbox(self, consumer: int) -> list[MessageRow]:
        seen = self.conn.execute(
            "SELECT last_seen_id FROM cursors WHERE consumer = ?", (consumer,)
        ).fetchone()
        last = int(seen["last_seen_id"]) if seen is not None else 0
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE addressee = ? AND id > ? ORDER BY id",
            (consumer, last),
        ).fetchall()
        if rows:
            self.conn.execute(
                "INSERT INTO cursors (consumer, last_seen_id) VALUES (?, ?) "
                "ON CONFLICT(consumer) DO UPDATE SET last_seen_id = excluded.last_seen_id",
                (consumer, int(rows[-1]["id"])),
            )
        return [MessageRow.model_validate(dict(r)) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bus.py -v`
Expected: PASS

- [ ] **Step 5: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/bus.py tests/unit/test_bus.py
git commit -m "Add SQLite task bus with atomic claim and message inbox"
```

---

### Task 6: Transcript log, load and repair

**Files:**
- Create: `ancalagon/transcript/transcript.py` (`Transcript`), `ancalagon/transcript/history.py` (`INTERRUPTED`, `load`, `repair`)
- Test: `tests/unit/test_repair.py`

**Interfaces:**
- Consumes: `ancalagon.contracts.Message`, `Role`, `Text`, `ToolUse`, `ToolResultBlock`
- Produces:
  - `Transcript(path, agent_id)` with `append(message: Message) -> None`, `close() -> None`
  - `load(path: pathlib.Path) -> list[Message]`
  - `repair(messages: list[Message]) -> list[Message]`

`repair` appends synthetic `interrupted` tool results when the last message is an assistant turn holding unanswered `ToolUse` blocks. Without it the API rejects a resumed conversation.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_repair.py`:

```python
import pathlib

from ancalagon.contracts import Message, Role, Text, ToolResultBlock, ToolUse
from ancalagon.transcript import Transcript, load, repair


def test_transcript_persists_per_message_and_repairs_interrupted_tool_calls(tmp_path: pathlib.Path):
    path = tmp_path / "transcript.jsonl"
    log = Transcript(path=path, agent_id=17)

    log.append(Message(role=Role.USER, blocks=[Text(text="go")], agent=17, seq=0, ts="t0"))
    assert path.read_text().count("\n") == 1

    log.append(
        Message(
            role=Role.ASSISTANT,
            blocks=[ToolUse(id="tu_1", name="ripgrep", arguments="{}")],
            agent=17,
            seq=1,
            ts="t1",
        )
    )
    log.close()

    loaded = load(path)
    assert [m.seq for m in loaded] == [0, 1]
    assert loaded[0].agent == 17

    repaired = repair(loaded)
    assert len(repaired) == 3
    assert repaired[2].role is Role.USER
    block = repaired[2].blocks[0]
    assert isinstance(block, ToolResultBlock)
    assert block.tool_use_id == "tu_1"
    assert block.is_error is True
    assert "interrupted" in block.content

    assert repair(repaired) == repaired
    assert repair([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_repair.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.transcript'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/transcript.py`:

```python
import pathlib

import ancalagon.contracts

INTERRUPTED = "interrupted: agent terminated before this tool returned"


class Transcript:
    def __init__(self, path: pathlib.Path, agent_id: int):
        self.path = path
        self.agent_id = agent_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a", encoding="utf-8")

    def append(self, message: ancalagon.contracts.Message) -> None:
        self.handle.write(message.model_dump_json() + "\n")
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def load(path: pathlib.Path) -> list[ancalagon.contracts.Message]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [ancalagon.contracts.Message.model_validate_json(line) for line in lines]


def repair(
    messages: list[ancalagon.contracts.Message],
) -> list[ancalagon.contracts.Message]:
    if not messages:
        return messages
    last = messages[-1]
    if last.role is not ancalagon.contracts.Role.ASSISTANT:
        return messages
    pending = [b for b in last.blocks if isinstance(b, ancalagon.contracts.ToolUse)]
    if not pending:
        return messages
    synthetic = ancalagon.contracts.Message(
        role=ancalagon.contracts.Role.USER,
        blocks=[
            ancalagon.contracts.ToolResultBlock(
                tool_use_id=b.id, content=INTERRUPTED, is_error=True
            )
            for b in pending
        ],
        agent=last.agent,
        seq=last.seq + 1,
        ts=last.ts,
    )
    return [*messages, synthetic]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_repair.py -v`
Expected: PASS

- [ ] **Step 5: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/transcript.py tests/unit/test_repair.py
git commit -m "Add append-and-flush transcript with interrupted-tool-call repair"
```

---

### Task 7: LLM protocol, FakeLLM and LiteLLM adapter

**Files:**
- Create: `ancalagon/llm/tool_schema.py` (`ToolSchema`), `ancalagon/llm/schema_of.py` (`schema_of`), `ancalagon/llm/llm.py` (`LLM` protocol), `ancalagon/llm/fake_llm.py` (`FakeLLM`), `ancalagon/llm/litellm_client.py` (`LiteLLMClient`, and the module-private `_to_wire`, `_to_arguments`)
- Test: covered by Task 10's `test_session_loop` via `FakeLLM`; no separate test file.

`schema_of(name: str, description: str, model: type[pydantic.BaseModel]) -> ToolSchema` returns `ToolSchema(name=name, description=description, parameters_json=json.dumps(model.model_json_schema()))`. It is the single definition — Tasks 8, 9 and 11 import it rather than redefining a local `_schema`.

**Interfaces:**
- Consumes: `ancalagon.contracts.Message`, `Reply`, `Text`, `ToolUse`, `ToolResultBlock`, `Role`
- Produces:
  - `ToolSchema(name: str, description: str, parameters_json: str)`
  - `LLM(typing.Protocol)` with `complete(system: str, messages: Sequence[Message], tools: Sequence[ToolSchema]) -> Reply`
  - `FakeLLM(replies: list[Reply])` — pops replies in order; raises if exhausted
  - `LiteLLMClient(model: str, max_tokens: int)`

LiteLLM normalises every provider to OpenAI shape, where `tool_calls[i].function.arguments` is already a JSON **string**. `_to_arguments` defends the case where a provider hands back a parsed mapping instead.

- [ ] **Step 1: Write the implementation**

Create `ancalagon/llm.py`:

```python
import collections.abc
import json
import typing

import pydantic

import ancalagon.contracts


class ToolSchema(pydantic.BaseModel, frozen=True):
    name: str
    description: str
    parameters_json: str


class LLM(typing.Protocol):
    def complete(
        self,
        system: str,
        messages: collections.abc.Sequence[ancalagon.contracts.Message],
        tools: collections.abc.Sequence[ToolSchema],
    ) -> ancalagon.contracts.Reply: ...


class FakeLLM:
    def __init__(self, replies: list[ancalagon.contracts.Reply]):
        self.replies = list(replies)
        self.seen: list[list[ancalagon.contracts.Message]] = []

    def complete(
        self,
        system: str,
        messages: collections.abc.Sequence[ancalagon.contracts.Message],
        tools: collections.abc.Sequence[ToolSchema],
    ) -> ancalagon.contracts.Reply:
        self.seen.append(list(messages))
        if not self.replies:
            raise RuntimeError("FakeLLM exhausted")
        return self.replies.pop(0)


def _to_wire(message: ancalagon.contracts.Message) -> list[dict[str, str]]:
    results = [b for b in message.blocks if isinstance(b, ancalagon.contracts.ToolResultBlock)]
    if results:
        return [
            {"role": "tool", "tool_call_id": b.tool_use_id, "content": b.content} for b in results
        ]
    text = "".join(b.text for b in message.blocks if isinstance(b, ancalagon.contracts.Text))
    return [{"role": message.role.value, "content": text}]


def _to_arguments(raw: str | collections.abc.Mapping[str, str]) -> str:
    return raw if isinstance(raw, str) else json.dumps(dict(raw))


class LiteLLMClient:
    def __init__(self, model: str, max_tokens: int):
        self.model = model
        self.max_tokens = max_tokens

    def complete(
        self,
        system: str,
        messages: collections.abc.Sequence[ancalagon.contracts.Message],
        tools: collections.abc.Sequence[ToolSchema],
    ) -> ancalagon.contracts.Reply:
        import litellm

        wire = [{"role": "system", "content": system}]
        for message in messages:
            wire.extend(_to_wire(message))
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": json.loads(t.parameters_json),
                },
            }
            for t in tools
        ]
        response = litellm.completion(
            model=self.model, messages=wire, tools=schemas, max_tokens=self.max_tokens
        )
        choice = response.choices[0]
        blocks: list[ancalagon.contracts.Block] = []
        if choice.message.content:
            blocks.append(ancalagon.contracts.Text(text=choice.message.content))
        for call in choice.message.tool_calls or []:
            blocks.append(
                ancalagon.contracts.ToolUse(
                    id=call.id,
                    name=call.function.name,
                    arguments=_to_arguments(call.function.arguments),
                )
            )
        return ancalagon.contracts.Reply(blocks=blocks, stop_reason=choice.finish_reason)
```

- [ ] **Step 2: Verify it imports and FakeLLM behaves**

Run:
```bash
uv run python -c "
from ancalagon.llm import FakeLLM
from ancalagon.contracts import Reply, Text
f = FakeLLM([Reply(blocks=[Text(text='hi')], stop_reason='stop')])
print(f.complete('sys', [], []))
"
```
Expected: prints a `Reply` with one `Text` block.

- [ ] **Step 3: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/llm.py
git commit -m "Add LLM protocol with FakeLLM and LiteLLM adapter"
```

---

### Task 8: Tool registry and file tools

**Files:**
- Create: `ancalagon/tools/registry/tool_context.py` (`ToolContext`), `ancalagon/tools/registry/tool.py` (`Tool` protocol), `ancalagon/tools/registry/registry.py` (`Registry`), `ancalagon/tools/files/path_args.py`, `write_args.py`, `edit_args.py`, `read_file.py`, `write_file.py`, `edit_file.py`, `delete_file.py`, `list_dir.py`
- Test: `tests/unit/test_tools.py`

Delete the local `_schema` helper shown in the task's code block; import `ancalagon.llm.schema_of.schema_of` instead.

**Interfaces:**
- Consumes: `ancalagon.contracts.ToolResult`, `ancalagon.workspace.Workspace`, `ancalagon.llm.ToolSchema`
- Produces:
  - `ToolContext(workspace, output_dir, summary_chars, agent_id)` with `write_output(tool_name, seq, text, suffix) -> pathlib.Path`
  - `Tool(typing.Protocol)`: attributes `name: str`, `description: str`; methods `schema() -> ToolSchema`, `run(arguments: str, ctx: ToolContext) -> ToolResult`
  - `Registry(tools: Sequence[Tool])` with `get(name) -> Tool`, `schemas() -> list[ToolSchema]`, `names() -> list[str]`
  - `ReadFile`, `WriteFile`, `EditFile`, `DeleteFile`, `ListDir`

Every tool validates its own arguments from the JSON string into a private Pydantic model inside `run`. That is what keeps `Any` out of the registry: the registry never sees a parsed argument structure.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tools.py`:

```python
import pathlib

from ancalagon.contracts import ToolResult
from ancalagon.tools.files import DeleteFile, EditFile, ListDir, ReadFile, WriteFile
from ancalagon.tools.registry import Registry, ToolContext
from ancalagon.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir()
    outputs = write_root / "outputs"
    outputs.mkdir()
    return ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=outputs,
        summary_chars=50,
        agent_id=17,
    )


def test_file_tools_round_trip_and_report_scope_violations_as_values(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    registry = Registry([ReadFile(), WriteFile(), EditFile(), DeleteFile(), ListDir()])

    assert sorted(registry.names()) == [
        "delete_file",
        "edit_file",
        "list_dir",
        "read_file",
        "write_file",
    ]
    assert {s.name for s in registry.schemas()} == set(registry.names())

    target = ctx.workspace.write_root / "note.txt"
    written = registry.get("write_file").run(
        f'{{"path": "{target}", "content": "hello world"}}', ctx
    )
    assert written.ok is True
    assert target.read_text() == "hello world"

    read = registry.get("read_file").run(f'{{"path": "{target}"}}', ctx)
    assert read.ok is True
    assert read.path.read_text() == "hello world"
    assert read.byte_count == 11

    edited = registry.get("edit_file").run(
        f'{{"path": "{target}", "old": "world", "new": "there"}}', ctx
    )
    assert edited.ok is True
    assert target.read_text() == "hello there"

    listed = registry.get("list_dir").run(f'{{"path": "{ctx.workspace.write_root}"}}', ctx)
    assert listed.ok is True
    assert "note.txt" in listed.path.read_text()

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    denied = registry.get("read_file").run(f'{{"path": "{outside}"}}', ctx)
    assert isinstance(denied, ToolResult)
    assert denied.ok is False
    assert "outside" in denied.error

    deleted = registry.get("delete_file").run(f'{{"path": "{target}"}}', ctx)
    assert deleted.ok is True
    assert not target.exists()

    long_content = "x" * 500
    big = ctx.workspace.write_root / "big.txt"
    big.write_text(long_content)
    result = registry.get("read_file").run(f'{{"path": "{big}"}}', ctx)
    assert result.truncated is True
    assert len(result.summary) <= 50
    assert result.path.read_text() == long_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.tools.registry'`

- [ ] **Step 3: Write `ancalagon/tools/registry.py`**

```python
import collections.abc
import itertools
import pathlib
import typing

import ancalagon.contracts
import ancalagon.llm
import ancalagon.workspace


class ToolContext:
    def __init__(
        self,
        workspace: ancalagon.workspace.Workspace,
        output_dir: pathlib.Path,
        summary_chars: int,
        agent_id: int,
    ):
        self.workspace = workspace
        self.output_dir = output_dir
        self.summary_chars = summary_chars
        self.agent_id = agent_id
        self.counter = itertools.count()

    def write_output(self, tool_name: str, text: str, suffix: str) -> pathlib.Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{next(self.counter):04d}-{tool_name}{suffix}"
        path.write_text(text, encoding="utf-8")
        return path

    def result(self, tool_name: str, text: str, suffix: str = ".txt") -> ancalagon.contracts.ToolResult:
        path = self.write_output(tool_name, text, suffix)
        return ancalagon.contracts.ToolResult(
            ok=True,
            summary=text[: self.summary_chars],
            path=path,
            byte_count=len(text.encode("utf-8")),
            truncated=len(text) > self.summary_chars,
        )

    def failure(self, tool_name: str, error: str) -> ancalagon.contracts.ToolResult:
        path = self.write_output(tool_name, error, ".err.txt")
        return ancalagon.contracts.ToolResult(ok=False, summary=error[: self.summary_chars], path=path, error=error)


class Tool(typing.Protocol):
    name: str
    description: str

    def schema(self) -> ancalagon.llm.ToolSchema: ...

    def run(self, arguments: str, ctx: ToolContext) -> ancalagon.contracts.ToolResult: ...


class Registry:
    def __init__(self, tools: collections.abc.Sequence[Tool]):
        self.tools = {t.name: t for t in tools}

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise KeyError(f"unknown tool {name}")
        return self.tools[name]

    def names(self) -> list[str]:
        return list(self.tools)

    def schemas(self) -> list[ancalagon.llm.ToolSchema]:
        return [t.schema() for t in self.tools.values()]
```

- [ ] **Step 4: Write `ancalagon/tools/files.py`**

```python
import pathlib

import pydantic

import ancalagon.contracts
import ancalagon.llm
import ancalagon.tools.registry
import ancalagon.workspace


class PathArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path


class WriteArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    content: str


class EditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    old: str
    new: str


def _schema(name: str, description: str, model: type[pydantic.BaseModel]) -> ancalagon.llm.ToolSchema:
    import json

    return ancalagon.llm.ToolSchema(
        name=name, description=description, parameters_json=json.dumps(model.model_json_schema())
    )


class ReadFile:
    name = "read_file"
    description = "Read a file inside the configured read roots."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, PathArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(self.name, path.read_text(encoding="utf-8"))


class WriteFile:
    name = "write_file"
    description = "Write a file inside the workspace write root."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, WriteArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = WriteArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")
        return ctx.result(self.name, f"wrote {len(args.content)} chars to {path}")


class EditFile:
    name = "edit_file"
    description = "Replace an exact substring in a file inside the workspace write root."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, EditArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = EditArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        original = path.read_text(encoding="utf-8")
        if args.old not in original:
            return ctx.failure(self.name, f"{args.old!r} not found in {path}")
        path.write_text(original.replace(args.old, args.new, 1), encoding="utf-8")
        return ctx.result(self.name, f"edited {path}")


class DeleteFile:
    name = "delete_file"
    description = "Delete a file inside the workspace write root."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, PathArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        path.unlink()
        return ctx.result(self.name, f"deleted {path}")


class ListDir:
    name = "list_dir"
    description = "List a directory inside the configured read roots."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, PathArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        entries = "\n".join(sorted(p.name for p in path.iterdir()))
        return ctx.result(self.name, entries)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tools.py -v`
Expected: PASS

- [ ] **Step 6: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/tools tests/unit/test_tools.py
git commit -m "Add tool registry and scope-checked file tools"
```

---

### Task 9: Search and parse tools

**Files:**
- Create: `ancalagon/tools/search/grep_args.py`, `sed_args.py`, `run_command.py` (the `_run` helper, renamed `run_command`), `ripgrep.py`, `ast_grep.py`, `sed.py`, `ancalagon/tools/parse/parse_args.py`, `ancalagon/tools/parse/tree_sitter_tool.py` (`LANGUAGES`, `TreeSitter`, and the module-private `_node_to_dict`, `_walk`)
- Modify: `tests/unit/test_tools.py` (add one test function)

Delete the local `_schema` helper shown in the task's code block; import `ancalagon.llm.schema_of.schema_of` instead.
- Modify: `pyproject.toml` (add `tree-sitter` and `tree-sitter-python` to dependencies)

**Interfaces:**
- Consumes: `ancalagon.tools.registry.Tool`, `ToolContext`
- Produces: `Ripgrep`, `AstGrep`, `Sed`, `TreeSitter`

`Sed` is stream-only. It never receives `-i` and never writes to its input, so it cannot mutate an artifact under analysis.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to `dependencies`:
```toml
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.23",
```
Then run `uv sync`.

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_tools.py`:

```python
from ancalagon.tools.parse import TreeSitter
from ancalagon.tools.search import Ripgrep, Sed


def test_search_and_parse_tools_write_outputs_and_never_mutate_inputs(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    source = ctx.workspace.write_root / "sample.py"
    source.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    before = source.read_text()

    found = Ripgrep().run(
        f'{{"pattern": "def (alpha|beta)", "roots": ["{ctx.workspace.write_root}"]}}', ctx
    )
    assert found.ok is True
    assert "alpha" in found.path.read_text()
    assert "beta" in found.path.read_text()

    missing = Ripgrep().run(f'{{"pattern": "zzz_absent", "roots": ["{ctx.workspace.write_root}"]}}', ctx)
    assert missing.ok is True
    assert missing.path.read_text() == ""

    streamed = Sed().run(f'{{"script": "s/alpha/gamma/", "path": "{source}"}}', ctx)
    assert streamed.ok is True
    assert "gamma" in streamed.path.read_text()
    assert source.read_text() == before

    parsed = TreeSitter().run(f'{{"path": "{source}", "language": "python"}}', ctx)
    assert parsed.ok is True
    assert '"type": "function_definition"' in parsed.path.read_text()

    denied = Sed().run(f'{{"script": "s/a/b/", "path": "{tmp_path / "outside.txt"}"}}', ctx)
    assert denied.ok is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.tools.search'`

- [ ] **Step 4: Write `ancalagon/tools/search.py`**

```python
import json
import pathlib
import subprocess

import pydantic

import ancalagon.contracts
import ancalagon.llm
import ancalagon.tools.registry
import ancalagon.workspace


class GrepArgs(pydantic.BaseModel, frozen=True):
    pattern: str
    roots: list[pathlib.Path]


class SedArgs(pydantic.BaseModel, frozen=True):
    script: str
    path: pathlib.Path


def _schema(name: str, description: str, model: type[pydantic.BaseModel]) -> ancalagon.llm.ToolSchema:
    return ancalagon.llm.ToolSchema(
        name=name, description=description, parameters_json=json.dumps(model.model_json_schema())
    )


def _run(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, capture_output=True, text=True)
    return completed.returncode, completed.stdout, completed.stderr


class Ripgrep:
    name = "ripgrep"
    description = "Search files by regular expression. Returns matching lines with paths."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, GrepArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = GrepArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = _run(["rg", "--line-number", "--no-heading", args.pattern, *roots])
        if code not in (0, 1):
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)


class AstGrep:
    name = "ast_grep"
    description = "Structural code search by AST pattern."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, GrepArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = GrepArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = _run(["ast-grep", "run", "--pattern", args.pattern, *roots])
        if code not in (0, 1):
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)


class Sed:
    name = "sed"
    description = "Apply a sed script to a file and write the transformed stream to a new file."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, SedArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = SedArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = _run(["sed", args.script, str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
```

- [ ] **Step 5: Write `ancalagon/tools/parse.py`**

```python
import json
import pathlib

import pydantic
import tree_sitter
import tree_sitter_python

import ancalagon.contracts
import ancalagon.llm
import ancalagon.tools.registry
import ancalagon.workspace

LANGUAGES = {"python": tree_sitter_python.language}


class ParseArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    language: str


def _node_to_dict(node: tree_sitter.Node) -> dict[str, str | int | list[str]]:
    return {
        "type": node.type,
        "start_byte": node.start_byte,
        "end_byte": node.end_byte,
        "children": [c.type for c in node.children],
    }


def _walk(node: tree_sitter.Node) -> list[dict[str, str | int | list[str]]]:
    collected = [_node_to_dict(node)]
    for child in node.children:
        collected.extend(_walk(child))
    return collected


class TreeSitter:
    name = "treesitter"
    description = "Parse a source file and emit its AST nodes as JSON."

    def schema(self) -> ancalagon.llm.ToolSchema:
        return ancalagon.llm.ToolSchema(
            name=self.name,
            description=self.description,
            parameters_json=json.dumps(ParseArgs.model_json_schema()),
        )

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = ParseArgs.model_validate_json(arguments)
        if args.language not in LANGUAGES:
            return ctx.failure(self.name, f"unsupported language {args.language}")
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ancalagon.workspace.ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        language = tree_sitter.Language(LANGUAGES[args.language]())
        parser = tree_sitter.Parser(language)
        tree = parser.parse(path.read_bytes())
        return ctx.result(self.name, json.dumps(_walk(tree.root_node), indent=2), ".json")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_tools.py -v`
Expected: PASS. Requires `rg` and `sed` on PATH; `ast-grep` is not exercised by this test.

- [ ] **Step 7: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add pyproject.toml uv.lock ancalagon/tools tests/unit/test_tools.py
git commit -m "Add ripgrep, ast-grep, stream-only sed and tree-sitter tools"
```

---

### Task 10: The session loop

**Files:**
- Create: `ancalagon/session.py`
- Test: `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: `ancalagon.contracts.*`, `ancalagon.llm.LLM`, `ancalagon.tools.registry.Registry`, `ancalagon.tools.registry.ToolContext`, `ancalagon.transcript.Transcript`
- Produces: `Session(spec, messages, transcript, agent_id, llm, registry, ctx, output_class)` with `run() -> Outcome`

Loop shape. Each iteration spends one turn. A reply with no `ToolUse` blocks ends the run and its text is parsed into `output_class`. When the turn budget hits zero, one final turn runs with **no tools offered** and an instruction to answer from what it has, producing `Exhausted`. Tool-call budget exhaustion is treated the same way. A tool raising is caught and returned to the agent as an error `ToolResultBlock`, never propagated.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_session_loop.py`:

```python
import pathlib

import pydantic

from ancalagon.contracts import (
    AgentSpec,
    Budget,
    Completed,
    Exhausted,
    Reply,
    Text,
    ToolUse,
)
from ancalagon.llm import FakeLLM
from ancalagon.session import Session
from ancalagon.tools.files import ReadFile
from ancalagon.tools.registry import Registry, ToolContext
from ancalagon.transcript import Transcript
from ancalagon.workspace import Workspace


class Verdict(pydantic.BaseModel):
    answer: str


def _session(tmp_path: pathlib.Path, replies: list[Reply], budget: Budget) -> Session:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = AgentSpec[Verdict](
        task_id="t1",
        behaviour="You answer questions.",
        goal="Answer it.",
        input=Verdict(answer="seed"),
        output="contracts.py:Verdict",
        budget=budget,
    )
    return Session(
        spec=spec,
        messages=[],
        transcript=Transcript(path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=FakeLLM(replies),
        registry=Registry([ReadFile()]),
        ctx=ctx,
        output_class=Verdict,
    )


def test_session_runs_tools_completes_and_forces_a_final_answer_when_exhausted(
    tmp_path: pathlib.Path,
):
    target = tmp_path / "ws"
    target.mkdir(exist_ok=True)
    (target / "data.txt").write_text("payload")

    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[ToolUse(id="tu_1", name="read_file", arguments=f'{{"path": "{target / "data.txt"}"}}')],
                stop_reason="tool_calls",
            ),
            Reply(blocks=[Text(text='{"answer": "payload"}')], stop_reason="stop"),
        ],
        Budget(turns=5, tool_calls=5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.answer == "payload"
    assert outcome.spent.turns == 2
    assert outcome.spent.tool_calls == 1

    transcript = (tmp_path / "transcript.jsonl").read_text()
    assert "read_file" in transcript
    assert transcript.count("\n") >= 4

    exhausting = _session(
        tmp_path / "second",
        [
            Reply(blocks=[ToolUse(id="tu_1", name="read_file", arguments='{"path": "/nope"}')], stop_reason="tool_calls"),
            Reply(blocks=[Text(text='{"answer": "best effort"}')], stop_reason="stop"),
        ],
        Budget(turns=1, tool_calls=5),
    )
    (tmp_path / "second").mkdir(exist_ok=True)
    forced = exhausting.run()
    assert isinstance(forced, Exhausted)
    assert forced.value.answer == "best effort"


def test_session_returns_tool_failures_to_the_agent_instead_of_raising(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[ToolUse(id="tu_1", name="read_file", arguments='{"path": "/etc/passwd"}')],
                stop_reason="tool_calls",
            ),
            Reply(blocks=[Text(text='{"answer": "denied"}')], stop_reason="stop"),
        ],
        Budget(turns=5, tool_calls=5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.answer == "denied"
    assert "outside" in (tmp_path / "transcript.jsonl").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_session_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.session'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/session.py`:

```python
import datetime
import logging

import pydantic

import ancalagon.contracts
import ancalagon.llm
import ancalagon.tools.registry
import ancalagon.transcript

LOGGER = logging.getLogger(__name__)

FINAL_INSTRUCTION = (
    "Your budget is exhausted. Answer now from what you already know, "
    "as a single JSON object matching the required output schema. No tools are available."
)


class Session:
    def __init__(
        self,
        spec: ancalagon.contracts.AgentSpec[pydantic.BaseModel],
        messages: list[ancalagon.contracts.Message],
        transcript: ancalagon.transcript.Transcript,
        agent_id: int,
        llm: ancalagon.llm.LLM,
        registry: ancalagon.tools.registry.Registry,
        ctx: ancalagon.tools.registry.ToolContext,
        output_class: type[pydantic.BaseModel],
    ):
        self.spec = spec
        self.messages = list(messages)
        self.transcript = transcript
        self.agent_id = agent_id
        self.llm = llm
        self.registry = registry
        self.ctx = ctx
        self.output_class = output_class
        self.remaining = spec.budget
        self.seq = len(messages)

    def _system(self) -> str:
        schema = self.output_class.model_json_schema()
        return (
            f"{self.spec.behaviour}\n\n"
            f"Goal: {self.spec.goal}\n\n"
            f"Input: {self.spec.input.model_dump_json()}\n\n"
            f"When finished, reply with a single JSON object matching this schema "
            f"and nothing else: {schema}"
        )

    def _record(
        self, role: ancalagon.contracts.Role, blocks: list[ancalagon.contracts.Block]
    ) -> None:
        message = ancalagon.contracts.Message(
            role=role,
            blocks=blocks,
            agent=self.agent_id,
            seq=self.seq,
            ts=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        self.seq += 1
        self.messages.append(message)
        self.transcript.append(message)

    def _spent(self) -> ancalagon.contracts.Budget:
        return ancalagon.contracts.Budget(
            turns=self.spec.budget.turns - self.remaining.turns,
            tool_calls=self.spec.budget.tool_calls - self.remaining.tool_calls,
        )

    def _text_of(self, reply: ancalagon.contracts.Reply) -> str:
        return "".join(
            b.text for b in reply.blocks if isinstance(b, ancalagon.contracts.Text)
        )

    def _run_tools(self, uses: list[ancalagon.contracts.ToolUse]) -> None:
        blocks: list[ancalagon.contracts.Block] = []
        for use in uses:
            self.remaining = self.remaining.spend_tool_call()
            try:
                result = self.registry.get(use.name).run(use.arguments, self.ctx)
            except Exception as exc:
                LOGGER.warning("tool %s raised: %s", use.name, exc)
                result = self.ctx.failure(use.name, f"{type(exc).__name__}: {exc}")
            blocks.append(
                ancalagon.contracts.ToolResultBlock(
                    tool_use_id=use.id,
                    content=f"{result.summary}\n[full output: {result.path}]",
                    is_error=not result.ok,
                )
            )
        self._record(ancalagon.contracts.Role.USER, blocks)

    def _final_turn(self) -> ancalagon.contracts.Outcome:
        self._record(
            ancalagon.contracts.Role.USER,
            [ancalagon.contracts.Text(text=FINAL_INSTRUCTION)],
        )
        reply = self.llm.complete(self._system(), self.messages, [])
        self._record(ancalagon.contracts.Role.ASSISTANT, reply.blocks)
        text = self._text_of(reply)
        try:
            value = self.output_class.model_validate_json(text)
        except pydantic.ValidationError as exc:
            return ancalagon.contracts.Failed(
                error=f"final answer did not validate: {exc}", summary=text[:200], spent=self._spent()
            )
        return ancalagon.contracts.Exhausted(
            value=value, summary=text[:200], spent=self._spent()
        )

    def run(self) -> ancalagon.contracts.Outcome:
        schemas = self.registry.schemas()
        while True:
            if self.remaining.turns_exhausted or self.remaining.tool_calls_exhausted:
                return self._final_turn()
            self.remaining = self.remaining.spend_turn()
            reply = self.llm.complete(self._system(), self.messages, schemas)
            self._record(ancalagon.contracts.Role.ASSISTANT, reply.blocks)
            uses = [b for b in reply.blocks if isinstance(b, ancalagon.contracts.ToolUse)]
            if uses:
                self._run_tools(uses)
                continue
            text = self._text_of(reply)
            try:
                value = self.output_class.model_validate_json(text)
            except pydantic.ValidationError as exc:
                LOGGER.info("output did not validate, asking again: %s", exc)
                self._record(
                    ancalagon.contracts.Role.USER,
                    [
                        ancalagon.contracts.Text(
                            text=f"That did not match the schema: {exc}. Reply with JSON only."
                        )
                    ],
                )
                continue
            return ancalagon.contracts.Completed(
                value=value, summary=text[:200], spent=self._spent()
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_session_loop.py -v`
Expected: PASS

- [ ] **Step 5: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/session.py tests/unit/test_session_loop.py
git commit -m "Add session loop with budget enforcement and forced final answer"
```

---

### Task 11: Worker entry point and delegate tools

**Files:**
- Create: `ancalagon/worker.py` (functions only), `ancalagon/tools/delegate/delegate_args.py`, `task_args.py`, `delegate.py` (`Delegate`), `check_task.py` (`CheckTask`), `collect_task.py` (`CollectTask`)
- Test: covered by Task 12's supervisor test and Task 13's integration test.

Delete the local `_schema` helper shown in the task's code block; import `ancalagon.llm.schema_of.schema_of` instead.

**Interfaces:**
- Consumes: everything above
- Produces:
  - `ancalagon.worker.main(run_dir, task_dir, agent_id, config_path) -> int` and `python -m ancalagon.worker`
  - `Delegate`, `CheckTask`, `CollectTask` tools

Worker contract: read `spec.json` from `--dir`, load and repair any existing `transcript.jsonl` in that directory, run one `Session`, write `outcome.json`, exit 0. Any exception writes an `outcome.json` of kind `failed` and exits 1.

- [ ] **Step 1: Write `ancalagon/worker.py`**

```python
import argparse
import logging
import pathlib
import sys

import pydantic

import ancalagon.config
import ancalagon.contracts
import ancalagon.llm
import ancalagon.session
import ancalagon.tools.delegate
import ancalagon.tools.files
import ancalagon.tools.parse
import ancalagon.tools.registry
import ancalagon.tools.search
import ancalagon.transcript
import ancalagon.workspace

LOGGER = logging.getLogger(__name__)


def build_registry(
    config: ancalagon.config.Config, run_dir: pathlib.Path, parent: int
) -> ancalagon.tools.registry.Registry:
    available: list[ancalagon.tools.registry.Tool] = [
        ancalagon.tools.files.ReadFile(),
        ancalagon.tools.files.WriteFile(),
        ancalagon.tools.files.EditFile(),
        ancalagon.tools.files.DeleteFile(),
        ancalagon.tools.files.ListDir(),
        ancalagon.tools.search.Ripgrep(),
        ancalagon.tools.search.AstGrep(),
        ancalagon.tools.search.Sed(),
        ancalagon.tools.parse.TreeSitter(),
        ancalagon.tools.delegate.Delegate(run_dir=run_dir, parent=parent),
        ancalagon.tools.delegate.CheckTask(run_dir=run_dir),
        ancalagon.tools.delegate.CollectTask(run_dir=run_dir),
    ]
    enabled = set(config.tools)
    return ancalagon.tools.registry.Registry(
        [t for t in available if not enabled or t.name in enabled]
    )


def main(run_dir: pathlib.Path, task_dir: pathlib.Path, agent_id: int, config_path: pathlib.Path) -> int:
    config = ancalagon.config.load_config(config_path)
    spec_path = task_dir / "spec.json"
    outcome_path = task_dir / "outcome.json"
    transcript_path = task_dir / "transcript.jsonl"
    log = ancalagon.transcript.Transcript(path=transcript_path, agent_id=agent_id)
    try:
        spec = ancalagon.contracts.AgentSpec[pydantic.BaseModel].model_validate_json(
            spec_path.read_text()
        )
        output_class = ancalagon.contracts.resolve_output_class(spec.output, task_dir)
        history = (
            ancalagon.transcript.repair(ancalagon.transcript.load(transcript_path))
            if transcript_path.exists()
            else []
        )
        ctx = ancalagon.tools.registry.ToolContext(
            workspace=ancalagon.workspace.Workspace.from_config(config),
            output_dir=task_dir / "tools",
            summary_chars=config.summary_chars,
            agent_id=agent_id,
        )
        session = ancalagon.session.Session(
            spec=spec,
            messages=history,
            transcript=log,
            agent_id=agent_id,
            llm=ancalagon.llm.LiteLLMClient(model=config.model, max_tokens=config.max_tokens),
            registry=build_registry(config, run_dir, parent=agent_id),
            ctx=ctx,
            output_class=output_class,
        )
        outcome = session.run()
        outcome_path.write_text(outcome.model_dump_json())
        return 0
    except Exception as exc:
        LOGGER.exception("worker failed")
        failure = ancalagon.contracts.Failed(
            error=f"{type(exc).__name__}: {exc}",
            summary=str(exc)[:200],
            spent=ancalagon.contracts.Budget(turns=0, tool_calls=0),
        )
        outcome_path.write_text(failure.model_dump_json())
        return 1
    finally:
        log.close()


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon.worker")
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--dir", type=pathlib.Path, required=True)
    parser.add_argument("--agent-id", type=int, required=True)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    args = parser.parse_args()
    return main(args.run_dir, args.dir, args.agent_id, args.config)


if __name__ == "__main__":
    sys.exit(cli())
```

- [ ] **Step 2: Write `ancalagon/tools/delegate.py`**

```python
import json
import pathlib

import pydantic

import ancalagon.bus
import ancalagon.contracts
import ancalagon.llm
import ancalagon.tools.registry


class DelegateArgs(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input_json: str
    output: str
    turns: int
    tool_calls: int


class TaskArgs(pydantic.BaseModel, frozen=True):
    task: int


def _schema(name: str, description: str, model: type[pydantic.BaseModel]) -> ancalagon.llm.ToolSchema:
    return ancalagon.llm.ToolSchema(
        name=name, description=description, parameters_json=json.dumps(model.model_json_schema())
    )


class Delegate:
    name = "delegate"
    description = "Queue a subagent task. Returns its task id immediately without waiting."

    def __init__(self, run_dir: pathlib.Path, parent: int):
        self.run_dir = run_dir
        self.parent = parent

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, DelegateArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = DelegateArgs.model_validate_json(arguments)
        task_dir = self.run_dir / "tasks" / args.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        spec = {
            "task_id": args.task_id,
            "behaviour": args.behaviour,
            "goal": args.goal,
            "input": json.loads(args.input_json),
            "output": args.output,
            "budget": {"turns": args.turns, "tool_calls": args.tool_calls},
            "tools": [],
        }
        (task_dir / "spec.json").write_text(json.dumps(spec))
        bus = ancalagon.bus.Bus.open(self.run_dir / "bus.db")
        task = bus.enqueue(task_dir, parent=self.parent)
        return ctx.result(self.name, f"queued task {task} at {task_dir}")


class CheckTask:
    name = "check_task"
    description = "Report the status of a delegated task without waiting."

    def __init__(self, run_dir: pathlib.Path):
        self.run_dir = run_dir

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, TaskArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = TaskArgs.model_validate_json(arguments)
        row = ancalagon.bus.Bus.open(self.run_dir / "bus.db").get(args.task)
        return ctx.result(self.name, f"task {row.id} is {row.status.value}: {row.summary}")


class CollectTask:
    name = "collect_task"
    description = "Read the outcome of a finished task. Reports if it is still running."

    def __init__(self, run_dir: pathlib.Path):
        self.run_dir = run_dir

    def schema(self) -> ancalagon.llm.ToolSchema:
        return _schema(self.name, self.description, TaskArgs)

    def run(
        self, arguments: str, ctx: ancalagon.tools.registry.ToolContext
    ) -> ancalagon.contracts.ToolResult:
        args = TaskArgs.model_validate_json(arguments)
        row = ancalagon.bus.Bus.open(self.run_dir / "bus.db").get(args.task)
        outcome = pathlib.Path(row.dir) / "outcome.json"
        if not outcome.exists():
            return ctx.failure(self.name, f"task {row.id} is {row.status.value}, no outcome yet")
        return ctx.result(self.name, outcome.read_text(), ".json")
```

- [ ] **Step 3: Verify it imports**

Run: `uv run python -c "import ancalagon.worker; print(ancalagon.worker.build_registry)"`
Expected: prints the function object.

- [ ] **Step 4: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/worker.py ancalagon/tools/delegate.py
git commit -m "Add worker entry point and delegate/check/collect tools"
```

---

### Task 12: Supervisor

**Files:**
- Create: `ancalagon/supervisor/process.py` (`Process` protocol), `spawner.py` (`Spawner` protocol), `clock.py` (`Clock` protocol), `system_clock.py` (`SystemClock`), `subprocess_spawner.py` (`SubprocessSpawner`), `supervisor.py` (`Supervisor`)
- Test: `tests/unit/test_supervisor.py`

The task's code block shows `run_until_idle` calling `self.bus.claim(limit=0)`, which is dead — a zero-limit claim always returns an empty list and opens a pointless transaction. Drop that call and gate solely on the queued-count query.

**Interfaces:**
- Consumes: `ancalagon.bus.Bus`, `TaskStatus`
- Produces: `Spawner(typing.Protocol)`, `SubprocessSpawner`, `Supervisor(bus, spawner, max_concurrent, timeout_s, poll_s)` with `tick() -> None`, `run_until_idle() -> None`, `shutdown() -> None`

The supervisor never retries. A crash is reported and nothing else. Its one autonomous act is killing a task that exceeds `timeout_s`. `Spawner` is a protocol so the test injects a fake instead of launching interpreters.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_supervisor.py`:

```python
import pathlib

from ancalagon.bus import Bus, TaskStatus
from ancalagon.supervisor import Supervisor


class FakeProcess:
    def __init__(self, pid: int, exit_after: int, code: int):
        self.pid = pid
        self.exit_after = exit_after
        self.code = code
        self.polls = 0
        self.killed = False

    def poll(self) -> int | None:
        self.polls += 1
        if self.killed:
            return -9
        return self.code if self.polls > self.exit_after else None

    def kill(self) -> None:
        self.killed = True


class FakeSpawner:
    def __init__(self, script: list[tuple[int, int]]):
        self.script = list(script)
        self.spawned: list[int] = []

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> FakeProcess:
        self.spawned.append(agent_id)
        exit_after, code = self.script.pop(0)
        return FakeProcess(pid=1000 + agent_id, exit_after=exit_after, code=code)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_supervisor_completes_reports_crashes_and_kills_wedged_tasks(tmp_path: pathlib.Path):
    bus = Bus.open(tmp_path / "bus.db")
    good = bus.enqueue(tmp_path / "tasks" / "good", parent=0)
    bad = bus.enqueue(tmp_path / "tasks" / "bad", parent=0)
    wedged = bus.enqueue(tmp_path / "tasks" / "wedged", parent=0)

    spawner = FakeSpawner([(0, 0), (0, 1), (10_000, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.run_until_idle()

    assert spawner.spawned == [good, bad, wedged]
    assert bus.get(good).status is TaskStatus.COMPLETED
    assert bus.get(good).exit_code == 0
    assert bus.get(bad).status is TaskStatus.CRASHED
    assert bus.get(bad).exit_code == 1
    assert bus.get(wedged).status is TaskStatus.TIMEOUT
    assert bus.get(wedged).pid == 1000 + wedged
    assert bus.running() == []
    assert [m.kind for m in bus.inbox(consumer=0)] == ["task_done", "task_done", "task_done"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_supervisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ancalagon.supervisor'`

- [ ] **Step 3: Write the implementation**

Create `ancalagon/supervisor.py`:

```python
import logging
import pathlib
import subprocess
import sys
import time
import typing

import ancalagon.bus

LOGGER = logging.getLogger(__name__)


class Process(typing.Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def kill(self) -> None: ...


class Spawner(typing.Protocol):
    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> Process: ...


class Clock(typing.Protocol):
    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def time(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class SubprocessSpawner:
    def __init__(self, run_dir: pathlib.Path, config_path: pathlib.Path):
        self.run_dir = run_dir
        self.config_path = config_path

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        stderr.parent.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ancalagon.worker",
                "--run-dir",
                str(self.run_dir),
                "--dir",
                str(task_dir),
                "--agent-id",
                str(agent_id),
                "--config",
                str(self.config_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=stderr.open("w"),
        )


class Supervisor:
    def __init__(
        self,
        bus: ancalagon.bus.Bus,
        spawner: Spawner,
        max_concurrent: int,
        timeout_s: int,
        poll_s: float = 0.05,
        clock: Clock = SystemClock(),
    ):
        self.bus = bus
        self.spawner = spawner
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.live: dict[int, Process] = {}
        self.started: dict[int, float] = {}

    def _start_queued(self) -> None:
        free = self.max_concurrent - len(self.live)
        if free <= 0:
            return
        for row in self.bus.claim(limit=free):
            process = self.spawner.spawn(pathlib.Path(row.dir), row.id)
            self.bus.mark_running(row.id, pid=process.pid)
            self.live[row.id] = process
            self.started[row.id] = self.clock.time()

    def _finish(self, task_id: int, status: ancalagon.bus.TaskStatus, code: int, summary: str) -> None:
        row = self.bus.get(task_id)
        self.bus.finish(task_id, status, exit_code=code, summary=summary)
        self.bus.post(
            sender=task_id, addressee=row.parent, kind="task_done", summary=summary, ref_path=row.dir
        )
        del self.live[task_id]
        del self.started[task_id]

    def _reap(self) -> None:
        for task_id, process in list(self.live.items()):
            code = process.poll()
            if code is None:
                if self.clock.time() - self.started[task_id] >= self.timeout_s:
                    LOGGER.warning("killing task %s after %ss", task_id, self.timeout_s)
                    process.kill()
                    self._finish(task_id, ancalagon.bus.TaskStatus.TIMEOUT, -9, "killed after timeout")
                continue
            status = (
                ancalagon.bus.TaskStatus.COMPLETED if code == 0 else ancalagon.bus.TaskStatus.CRASHED
            )
            self._finish(task_id, status, code, f"exited {code}")

    def tick(self) -> None:
        self._start_queued()
        self._reap()

    def run_until_idle(self) -> None:
        while True:
            self.tick()
            if not self.live and not self.bus.claim(limit=0):
                queued = self.bus.conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE status = ?",
                    (ancalagon.bus.TaskStatus.QUEUED.value,),
                ).fetchone()
                if int(queued["n"]) == 0:
                    return
            self.clock.sleep(self.poll_s)

    def shutdown(self) -> None:
        for task_id, process in list(self.live.items()):
            process.kill()
            self._finish(task_id, ancalagon.bus.TaskStatus.ABANDONED, -9, "abandoned at shutdown")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_supervisor.py -v`
Expected: PASS

- [ ] **Step 5: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/supervisor.py tests/unit/test_supervisor.py
git commit -m "Add supervisor that spawns, reaps and kills without retrying"
```

---

### Task 13: CLI and end-to-end integration

**Files:**
- Create: `ancalagon/cli.py`, `tests/integration/test_end_to_end.py`, `ancalagon.example.toml`
- Modify: `pyproject.toml` (add `[project.scripts]`)

**Interfaces:**
- Consumes: everything above
- Produces: `ancalagon run --config <toml> --goal <text>`; `ancalagon.cli.main(config_path, goal) -> int`

The CLI creates a run directory, writes the root task's `spec.json` with `output` pointing at a generated `contracts.py` containing `FreeText`, starts a supervisor in a background thread, enqueues the root task, waits for idle, then prints the root outcome.

- [ ] **Step 1: Write `ancalagon/cli.py`**

```python
import argparse
import json
import logging
import pathlib
import sys
import threading

import ancalagon.bus
import ancalagon.config
import ancalagon.supervisor

LOGGER = logging.getLogger(__name__)

ROOT_CONTRACTS = "import pydantic\n\n\nclass FreeText(pydantic.BaseModel):\n    text: str\n"

ROOT_BEHAVIOUR = (
    "You are a reverse engineering agent. Use your tools to investigate, and delegate "
    "focused subtasks with the delegate tool when a question is self-contained."
)


def _new_run_dir(write_root: pathlib.Path) -> pathlib.Path:
    runs = write_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[2:]) for p in runs.glob("r_*") if p.name[2:].isdigit()]
    run_dir = runs / f"r_{max(existing, default=0) + 1:04d}"
    run_dir.mkdir()
    return run_dir


def main(config_path: pathlib.Path, goal: str) -> int:
    logging.basicConfig(level=logging.INFO)
    config = ancalagon.config.load_config(config_path)
    run_dir = _new_run_dir(config.write_root)
    task_dir = run_dir / "tasks" / "root"
    task_dir.mkdir(parents=True)
    (task_dir / "contracts.py").write_text(ROOT_CONTRACTS)
    (task_dir / "spec.json").write_text(
        json.dumps(
            {
                "task_id": "root",
                "behaviour": ROOT_BEHAVIOUR,
                "goal": goal,
                "input": {"text": goal},
                "output": "contracts.py:FreeText",
                "budget": {"turns": config.budget.turns, "tool_calls": config.budget.tool_calls},
                "tools": [],
            }
        )
    )

    bus = ancalagon.bus.Bus.open(run_dir / "bus.db")
    supervisor = ancalagon.supervisor.Supervisor(
        bus=ancalagon.bus.Bus.open(run_dir / "bus.db"),
        spawner=ancalagon.supervisor.SubprocessSpawner(run_dir=run_dir, config_path=config_path),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
    )
    bus.enqueue(task_dir, parent=0)
    thread = threading.Thread(target=supervisor.run_until_idle, daemon=True)
    thread.start()
    thread.join()
    supervisor.shutdown()

    outcome = task_dir / "outcome.json"
    if not outcome.exists():
        LOGGER.error("root task produced no outcome; see %s", task_dir)
        return 1
    sys.stdout.write(outcome.read_text() + "\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--goal", type=str, required=True)
    args = parser.parse_args()
    return main(args.config, args.goal)


if __name__ == "__main__":
    sys.exit(cli())
```

- [ ] **Step 2: Add the console script to `pyproject.toml`**

```toml
[project.scripts]
ancalagon = "ancalagon.cli:cli"
```
Then run `uv sync`.

- [ ] **Step 3: Write `ancalagon.example.toml`**

```toml
[workspace]
write_root = "./ws"
read_roots = ["./artifacts"]

[model]
name = "claude-opus-5"
max_tokens = 8000

[budget]
turns = 20
tool_calls = 60

[limits]
max_concurrent_agents = 1
agent_timeout_s = 3600
max_depth = 1
summary_chars = 1000

[tools]
enabled = []
```

- [ ] **Step 4: Write the integration test**

Create `tests/integration/test_end_to_end.py`:

```python
import json
import os
import pathlib
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a live model credential"
)
def test_root_agent_delegates_and_returns_an_outcome(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    artifacts = tmp_path / "artifacts"
    write_root.mkdir()
    artifacts.mkdir()
    (artifacts / "graph.json").write_text(
        json.dumps({"nodes": [{"id": "a", "body": "reads a file"}, {"id": "b", "body": "writes a file"}]})
    )

    config = tmp_path / "ancalagon.toml"
    config.write_text(
        f'''
[workspace]
write_root = "{write_root}"
read_roots = ["{artifacts}"]

[model]
name = "claude-opus-5"
max_tokens = 4000

[budget]
turns = 8
tool_calls = 20

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
summary_chars = 1000

[tools]
enabled = []
'''
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ancalagon.cli",
            "run",
            "--config",
            str(config),
            "--goal",
            f"Read {artifacts / 'graph.json'} and state in one sentence what node 'a' does.",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr

    outcome = json.loads(completed.stdout)
    assert outcome["kind"] in ("completed", "exhausted")
    assert "file" in outcome["value"]["text"].lower()

    run_dir = next((write_root / "runs").iterdir())
    assert (run_dir / "bus.db").exists()
    assert (run_dir / "tasks" / "root" / "transcript.jsonl").read_text().count("\n") >= 2
```

- [ ] **Step 5: Run the unit suite and confirm the integration test skips without credentials**

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
```
Expected: unit suite PASS; integration test reports `1 skipped` when `ANTHROPIC_API_KEY` is unset.

- [ ] **Step 6: Run the integration test for real**

```bash
ANTHROPIC_API_KEY=... uv run pytest tests/integration -q -s
```
Expected: PASS. If the agent fails to produce schema-valid JSON, the fix belongs in `Session._system()` — do not loosen the assertion.

- [ ] **Step 7: Run gates and commit**

```bash
uv run black . && uv run pyright && uv run pytest tests/unit -q
git add ancalagon/cli.py ancalagon.example.toml pyproject.toml uv.lock tests/integration
git commit -m "Add CLI entry point and end-to-end integration test"
```

---

### Task 14: README and LoC audit

**Files:**
- Create: `README.md`
- Test: none

**Interfaces:**
- Consumes: everything
- Produces: documentation and a recorded line count against the ceiling

- [ ] **Step 1: Measure the implementation against the ceiling**

```bash
find ancalagon -name '*.py' | xargs wc -l | sort -n
```
Expected: total under ~1100. If a module exceeds its spec allocation, that is a signal to re-read the guardrails — reduce the code, do not raise the ceiling.

- [ ] **Step 2: Write `README.md`**

```markdown
# Ancalagon

An agent harness for reverse engineering.

## What it does

Give it a data structure and a goal. An agent investigates with tools — ripgrep,
ast-grep, tree-sitter, sed, scoped file access — and delegates focused subtasks to
isolated subagent processes.

## Running

```bash
uv sync
cp ancalagon.example.toml ancalagon.toml   # edit write_root and read_roots
uv run ancalagon run --config ancalagon.toml --goal "..."
```

## How it works

Three kinds of process, communicating only through SQLite rows and files:

- **Root agent** — reasons, uses tools, delegates.
- **Supervisor** — spawns, reaps, kills on timeout. Never retries; a crash is
  reported and the parent decides. The only module that constructs `Popen`.
- **Worker** — one agent session per process, one attempt at one task.

There is no IPC. A parent writes `spec.json` and enqueues a row; a worker writes
`outcome.json` and `transcript.jsonl`. Nothing blocks.

## Inspecting a run

Everything is on disk and in one SQLite file:

```bash
sqlite3 ws/runs/r_0001/bus.db "select id, dir, status, exit_code, summary from tasks"
rg '"agent": 17' ws/runs/r_0001/tasks/*/transcript.jsonl
```

## Layout

```
ws/runs/<run>/
    bus.db
    tasks/<task_id>/
        spec.json  outcome.json  transcript.jsonl  stderr-<agent>.log  tools/
```

## Design

See `docs/superpowers/specs/2026-08-02-ancalagon-agent-harness-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Add README"
```

---

## Self-review

**Spec coverage.** Architecture → Tasks 11–13. Communication via rows and files → Tasks 5, 11, 12. `ask_parent` cut → nothing implements it, correct. No auto-restart → Task 12 asserts crash reports without requeue. Task model and directory identity → Tasks 11, 13. Resumption and `repair` → Task 6, wired in Task 11. Persistence per message → Task 6. Contracts → Task 2. Schema and migrations → Tasks 4, 5. Budgets with forced final turn → Tasks 2, 10. Tools and two-scope enforcement → Tasks 3, 8, 9. Config → Task 3. LiteLLM behind a protocol → Task 7. Testing list → one test per task, nine total. LoC ceiling → Task 14.

**Gap found and closed.** The spec lists `max_depth` in config but no task enforced it. It is loaded in Task 3 and carried in `Config`, but nothing checks it, because depth enforcement needs the parent's depth threaded through `delegate` — which only matters once harnesses nest. Recorded here rather than silently dropped: **`max_depth` is loaded but not enforced in Plan A**, and enforcement belongs in Plan B where `run_harness` introduces the second level.

**Type consistency.** `ToolContext.result`/`failure` used in Tasks 8, 9, 11 match Task 8's definitions. `Bus` methods used in Task 12 match Task 5. `Session.__init__` in Task 11 matches Task 10. `resolve_output_class` in Task 11 matches Task 2. `Spawner.spawn(task_dir, agent_id)` matches between Task 12's fake and `SubprocessSpawner`.

**Known risk.** `AgentSpec[pydantic.BaseModel]` in the worker validates `input` as a bare `BaseModel`, which accepts any object shape without checking fields. This is deliberate: the worker cannot know the input class, and the input is the caller's own construction. The *output* is where validation matters, and it is validated against the resolved class on both sides.
