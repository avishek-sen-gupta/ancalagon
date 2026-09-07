# An Answer Too Large To Emit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent whose answer contract is too large to emit in one completion build that answer on disk across many turns and submit a pointer to it, validated against a JSON Schema by a declared hook.

**Architecture:** Three additions and one subtraction, all outside the core. `edit_json` mutates a JSON file in place through jq. `AnswerFile` is a three-field answer contract carrying a status, a sentence and a path, submitted by a new terminal tool `submit_answer_as_file`. `adheres_to_schema` is a `before` hook that reads the file and checks it against the schema the task's input named. The subtraction comes first: `submit_answer` stops being injected into every role, so a role names exactly one terminal submit tool and there is one route to a completed run.

**Tech Stack:** Python 3.13, Pydantic v2, jq 1.8.2 on PATH, `jsonschema` 4.26, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-07-an-answer-too-large-to-emit-design.md`

## Global Constraints

- Pyright strict, zero errors. `Any` and `object` are banned outright — no `from typing import Any`, no `dict[str, Any]`, no hand-rolled recursive JSON alias.
- Every generic parameterised: `dict[str, int]`, `tuple[str, ...]`, never bare `dict`/`tuple`.
- No comments except a one-line header on a class or module stating its purpose. No docstrings.
- Pydantic models are `frozen=True`. Dataclasses are `frozen=True`.
- Domain code says `pathlib.PurePath`, which has no `read_text`. Only `ancalagon/fs/real_file_system.py` touches a file; tools reach the filesystem through `ctx.workspace`.
- Enums for fixed string sets, not raw strings. Constants instead of magic strings.
- No `None` defaults, no `None` returns from non-`None` signatures, no defensive `isinstance` coercion, no `is not None` guards added to make a test pass.
- Functional style: comprehensions, `map`, `filter`; no accumulating `for` loops.
- Few tests, each covering a whole behaviour. Concrete value assertions, not `assert x is not None`.
- One class per file. Fully qualified imports, no relative imports.
- Verification for every task: `uv run python -m black . && uv run pyright && uv run lint-imports && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration`. The integration suite takes about a minute and is not optional — two previous plans skipped it and both let a regression through.
- Never put an identifier from an externally analysed codebase into a tracked artifact. Test roles and fixtures use generic names.

---

### Task 1: A role declares its own submit tool

`build_registry` adds `submit_answer` to every role whether it asked for it or not. That injection is why the terminal tool cannot be chosen per role, and it has to go before a second terminal tool exists. After this task a role that runs a session names its submit tool in config or `check_contracts` rejects the config.

A deterministic role — one with `run` set — never builds a registry and never answers through a tool, so the requirement does not apply to it.

**Files:**
- Modify: `ancalagon/worker.py:136`
- Modify: `ancalagon/cli.py:152-166` (`check_contracts`), adding `_submit_fault` above it
- Modify: `tests/integration/test_end_to_end.py:88`, `tests/integration/test_local_model_escalation.py:50`, `tests/integration/test_scripted_escalation.py:66,74`, `tests/integration/test_scripted_hooks.py:64`
- Modify: `tests/unit/test_config_load.py`, `tests/unit/test_hooks.py` — every role fixture that runs a session
- Modify: `README.md:135`, `README.md:218`, `README.md:124` (the mermaid node), `docs/architecture.md` near line 439
- Test: `tests/unit/test_config_load.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ancalagon.cli._submit_fault(name: str, role: Role) -> str` — returns `""` when the role is fine, otherwise a message prefixed `[roles.<name>]`. Task 3 widens it to accept the second tool name.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_config_load.py`, alongside the existing config-fault tests:

```python
def test_a_session_role_must_name_a_submit_tool(tmp_path: pathlib.Path):
    text = """
[workspace]
write_root = "./ws"
read_roots = ["./src"]

[model]
name = "fake/model"

[roles.analyst]
behaviour = "You answer."
tools = ["read_file"]
budget = { turns = 3, tool_calls = 3 }

[roles.transformer]
behaviour = "You transform."
run = { module = "runkit.runners", name = "double" }
tools = []
budget = { turns = 1, tool_calls = 1 }

[run]
goal_file = "./goal.md"
role = "analyst"
"""
    path = tmp_path / "ancalagon.toml"
    path.write_text(text)
    config = load_config(pathlib.PurePath(path), RealFileSystem())

    with pytest.raises(ValueError) as raised:
        check_contracts(config, RealFileSystem())

    assert "[roles.analyst]" in str(raised.value)
    assert "submit_answer" in str(raised.value)
    assert "[roles.transformer]" not in str(raised.value)
```

Import `check_contracts` from `ancalagon.cli` at the top of the file if it is not already imported. The `transformer` role is in the fixture on purpose: it proves the check exempts a deterministic role rather than merely passing the one case the test cares about.

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run --no-sync python -m pytest tests/unit/test_config_load.py::test_a_session_role_must_name_a_submit_tool -v
```

Expected: FAIL — `DID NOT RAISE <class 'ValueError'>`, because nothing checks this yet.

- [ ] **Step 3: Add the check**

In `ancalagon/cli.py`, above `check_contracts`:

```python
def _submit_fault(name: str, role: Role) -> str:
    if role.run != NO_RUN or SubmitAnswer.name in role.tools:
        return ""
    return (
        f"[roles.{name}] tools: a role that runs a session must name {SubmitAnswer.name}; "
        f"named: {sorted(role.tools)}"
    )
```

`role.run != NO_RUN` asks whether the role has a real run function; `NO_RUN` is the null-object `FunctionRef`. Use `!=`, not `is not` — `_run_fault` at `ancalagon/cli.py:110` already compares by value and these two should read the same. `NO_RUN` is already imported at `ancalagon/cli.py:17`; add the `SubmitAnswer` import from `ancalagon.tools.submit.submit_answer`.

Then add the clause to `check_contracts`'s `or` chain, after the `_run_fault` clause and before `_hook_fault`:

```python
        or [fault for name, role in config.roles.items() if (fault := _submit_fault(name, role))]
```

- [ ] **Step 4: Stop injecting the tool**

`ancalagon/worker.py:136`:

```python
    wanted = set(spec.role.tools) | {Idle.name}
```

`Idle` stays injected. It is not a way to answer — it suspends an agent that is waiting for a child — and nothing in this plan concerns it.

- [ ] **Step 5: Run it and watch it pass, then find everything the injection was carrying**

```bash
uv run --no-sync python -m pytest tests/unit/test_config_load.py::test_a_session_role_must_name_a_submit_tool -v
uv run --no-sync python -m pytest tests/unit -q
uv run --no-sync python -m pytest tests/integration -q
```

Every failure is a role fixture that relied on the injection. Add `"submit_answer"` to that role's `tools` list. The candidate sites, found with `grep -rn 'tools = \[' tests/`:

| File | Line | Current |
|---|---|---|
| `tests/integration/test_end_to_end.py` | 88 | `tools = ["read_file"]` |
| `tests/integration/test_local_model_escalation.py` | 50 | `tools = ["need_input"]` |
| `tests/integration/test_scripted_escalation.py` | 66 | `tools = ["delegate_investigate", "need_input", "answer_task"]` |
| `tests/integration/test_scripted_escalation.py` | 74 | `tools = ["need_input"]` |
| `tests/integration/test_scripted_hooks.py` | 64 | `tools = []` |
| `tests/unit/test_hooks.py` | 163 | `tools = ["ripgrep"]` |
| `tests/unit/test_config_load.py` | 125, 130, 164, 301 | various |

Change only what the run actually reports. Several of those `test_config_load.py` fixtures assert that `load_config` raises before `check_contracts` is ever reached, so they will not fail and should be left alone; `:301` (`PROSE_ROLE`) only needs the tool if the test using it calls `check_contracts`. Let the failing tests pick the sites rather than editing the whole table.

Leave `tools = []` alone at `tests/integration/test_blackboard.py:84`, `tests/integration/test_deterministic_loop.py:143`, `tests/unit/test_config_load.py:243` and `tests/unit/test_deterministic.py:82` — all four are deterministic roles with `run` set, which is exactly the exemption the new test pins.

Do not change `tests/unit/test_session_loop.py`. Those sessions build their `Registry` by hand and never go through `build_registry`.

- [ ] **Step 6: Update the documents that promised the injection**

`README.md:135` currently says `submit_answer` and `idle` arrive regardless. Replace with:

```markdown
- `tools = []` means *no tools*, not all of them. `idle` arrives regardless; a terminal submit
  tool does not — a role that runs a session names one, and `check_contracts` rejects a role
  that names none. There is one way out of a run and the role chooses which.
```

`README.md:218` — the sentence introducing the tool table says `submit_answer` and `idle` arrive whatever a role names. Narrow it to `idle`.

`README.md:124` — the mermaid node reads `registry - exactly these,<br/>plus submit_answer and idle`. Change to `registry - exactly these,<br/>plus idle`.

`docs/architecture.md` near line 439 — the paragraph describing which tools reach the registry. Say that the submit tool is named by the role rather than added for it, and that `check_contracts` catches a role that names none before any agent starts.

- [ ] **Step 7: Verify and commit**

```bash
uv run --no-sync python -m black . && uv run --no-sync pyright && uv run --no-sync lint-imports
uv run --no-sync python -m pytest tests/unit -q && uv run --no-sync python -m pytest tests/integration -q
git add -A && git commit
```

Commit message subject: `Make a role name its own submit tool`. Body should say why: a second terminal tool is coming, and a tool the worker injects cannot be chosen per role.

- [ ] **Step 8: Tell the user about their untracked config**

`~/code/tw-cc-codes/kfield-agent/ancalagon.toml` declares five roles and none of them names `submit_answer`. It is untracked and outside this repository, so it is **not** part of this commit. Report that its five roles each need `"submit_answer"` added to `tools`, and let the user make the edit or ask you to.

---

### Task 2: `edit_json`

A tool that mutates one place in a JSON file, so a large structure is assembled across many small calls rather than emitted in one.

The pointer never reaches jq's program text. The program is one of three fixed strings and both the path and the value arrive through `--argjson`, so nothing the model writes is interpolated into a jq expression. Verified: `jq --argjson v -1 'setpath($p;$v)'` works, and `jq --argjson v --slurp` fails with `invalid JSON text passed to --argjson` rather than consuming `--slurp` as an option — so no leading-dash guard is needed and jq's own message is the failure the model reads.

**Files:**
- Create: `ancalagon/tools/artifacts/json_op.py`
- Create: `ancalagon/tools/artifacts/json_path.py`
- Create: `ancalagon/tools/artifacts/json_edit_args.py`
- Create: `ancalagon/tools/artifacts/edit_json.py`
- Modify: `ancalagon/worker.py` — import and one `bound_for` line in `available_tools`
- Modify: `README.md` — one row in the tool table near line 256
- Test: `tests/unit/test_json_edit.py`

Note the name: `ancalagon/tools/files/edit_args.py` already holds an `EditArgs` for `edit_file`. This one is `JsonEditArgs` in `json_edit_args.py` so there are never two classes called `EditArgs`.

**Interfaces:**
- Consumes: `ToolContext` and `Tool[ArgsT]` as every other tool does; `run_command` from `ancalagon.tools.search.run_command`.
- Produces:
  - `ancalagon.tools.artifacts.json_op.JsonOp` — `StrEnum` with `SET = "set"`, `APPEND = "append"`, `REMOVE = "remove"`.
  - `ancalagon.tools.artifacts.json_path.JsonPath` — `pydantic.RootModel[tuple[str | int, ...]]`, `model_dump_json()` emits a bare array.
  - `ancalagon.tools.artifacts.json_path.path_of(pointer: str) -> JsonPath`.
  - `ancalagon.tools.artifacts.json_edit_args.JsonEditArgs` — `path: pathlib.PurePath`, `op: JsonOp`, `pointer: str`, `value: str = ""`.
  - `ancalagon.tools.artifacts.edit_json.EditJson` — `name = "edit_json"`, `cost = 1`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_json_edit.py`:

```python
import pathlib

import pydantic
import pytest

from ancalagon.clock.fake_clock import FakeClock
from ancalagon.tools.artifacts.edit_json import EditJson
from ancalagon.tools.artifacts.json_edit_args import JsonEditArgs
from ancalagon.tools.artifacts.json_op import JsonOp
from ancalagon.tools.artifacts.json_path import JsonPath, path_of
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )


def test_a_json_pointer_becomes_the_path_jq_indexes_with():
    assert path_of("/values/0/name") == JsonPath(root=("values", 0, "name"))
    assert path_of("") == JsonPath(root=())
    assert path_of("/a~1b/c~0d") == JsonPath(root=("a/b", "c~d"))
    assert path_of("/values/0/name").model_dump_json() == '["values",0,"name"]'

    with pytest.raises(pydantic.ValidationError):
        JsonEditArgs(path=pathlib.PurePath("x.json"), op=JsonOp.SET, pointer="values/0")


def test_edit_json_sets_appends_and_removes_in_place(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    target = tmp_path / "ws" / "answer.json"
    target.write_text('{"values": [{"name": "a"}], "complete": false}')
    tool = EditJson()

    setting = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath(target),
            op=JsonOp.SET,
            pointer="/values/0/name",
            value='"renamed"',
        ),
        ctx,
    )
    assert setting.ok
    appending = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath(target),
            op=JsonOp.APPEND,
            pointer="/values",
            value='{"name": "b"}',
        ),
        ctx,
    )
    assert appending.ok
    removing = tool.run(
        JsonEditArgs(path=pathlib.PurePath(target), op=JsonOp.REMOVE, pointer="/complete"),
        ctx,
    )
    assert removing.ok

    assert json.loads(target.read_text()) == {
        "values": [{"name": "renamed"}, {"name": "b"}]
    }


def test_edit_json_refuses_a_path_outside_the_write_root_and_a_value_jq_rejects(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    target = tmp_path / "ws" / "answer.json"
    target.write_text("{}")
    tool = EditJson()

    outside = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath("/etc/passwd"), op=JsonOp.SET, pointer="/x", value="1"
        ),
        ctx,
    )
    assert not outside.ok
    assert "/etc/passwd" in outside.error

    bad = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath(target), op=JsonOp.SET, pointer="/x", value="not json"
        ),
        ctx,
    )
    assert not bad.ok
    assert "argjson" in bad.error
    assert target.read_text() == "{}"
```

Add `import json` to the imports. The last assertion is the one that matters most in that test: a rejected edit must leave the file untouched, which is only true because the write happens after jq's exit code is checked.

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run --no-sync python -m pytest tests/unit/test_json_edit.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'ancalagon.tools.artifacts.edit_json'`.

- [ ] **Step 3: The enum**

`ancalagon/tools/artifacts/json_op.py`:

```python
# What edit_json does at the pointer it is given.
import enum


class JsonOp(enum.StrEnum):
    SET = "set"
    APPEND = "append"
    REMOVE = "remove"
```

- [ ] **Step 4: The pointer**

`ancalagon/tools/artifacts/json_path.py`:

```python
# A JSON Pointer resolved into the path jq indexes with.
import pydantic


class JsonPath(pydantic.RootModel[tuple[str | int, ...]], frozen=True):
    pass


def path_of(pointer: str) -> JsonPath:
    return JsonPath(
        root=tuple(
            int(token) if token.isdigit() else token.replace("~1", "/").replace("~0", "~")
            for token in pointer.split("/")[1:]
        )
    )
```

`pointer.split("/")[1:]` drops the empty segment before the leading slash, so `""` yields `()` — the whole document — and `/a/b` yields `("a", "b")`. `~1` is unescaped before `~0`, which is the order RFC 6901 requires. Verified: `JsonPath(root=("values", 0, "name")).model_dump_json()` is `["values",0,"name"]`, and `frozen=True` as a class keyword reaches `model_config` on a `RootModel`.

- [ ] **Step 5: The arguments**

`ancalagon/tools/artifacts/json_edit_args.py`:

```python
# Arguments for one in-place edit of a JSON file.
import pathlib

import pydantic

from ancalagon.tools.artifacts.json_op import JsonOp


class JsonEditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    op: JsonOp
    pointer: str = pydantic.Field(
        pattern="^(/[^/]*)*$",
        description="RFC 6901 JSON Pointer, e.g. /values/0/name. Empty means the whole document.",
    )
    value: str = pydantic.Field(
        default="",
        description="The JSON text to write, e.g. '\"text\"', '42' or '{\"a\": 1}'. "
        "Leave empty for remove.",
    )
```

The `pattern` is the constraint, on the field, where the model sees it before it calls — not a check inside `run` that can only report afterwards. `^(/[^/]*)*$` accepts `""`, `/a` and `/a/b` and rejects `a/b`.

- [ ] **Step 6: The tool**

`ancalagon/tools/artifacts/edit_json.py`:

```python
# Edits a JSON file in place with jq, so a large structure is built across many small calls.
import collections.abc

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.json_edit_args import JsonEditArgs
from ancalagon.tools.artifacts.json_op import JsonOp
from ancalagon.tools.artifacts.json_path import path_of
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError

PROGRAMS: collections.abc.Mapping[JsonOp, str] = {
    JsonOp.SET: "setpath($p; $v)",
    JsonOp.APPEND: "setpath($p; getpath($p) + [$v])",
    JsonOp.REMOVE: "delpaths([$p])",
}


class EditJson(Tool[JsonEditArgs]):
    name = "edit_json"
    description = (
        "Change one place in a JSON file inside the write root, leaving the rest alone. "
        "Use this to build a large answer across many small calls instead of writing the "
        "whole file each time. set replaces what is at the pointer, append adds to the "
        "array there, remove deletes the key. The file must already exist; write_file with "
        "{} creates it."
    )
    cost = 1
    args_model = JsonEditArgs

    def run(self, args: JsonEditArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        value = [] if args.op is JsonOp.REMOVE else ["--argjson", "v", args.value]
        code, out, err = run_command(
            [
                "jq",
                "--argjson",
                "p",
                path_of(args.pointer).model_dump_json(),
                *value,
                PROGRAMS[args.op],
                str(path),
            ]
        )
        if code != 0:
            return ctx.failure(self.name, err)
        ctx.workspace.write_text(path, out)
        return ctx.result(self.name, f"{args.op} at {args.pointer or '/'} in {path}")
```

`value: list[str]` needs no annotation — Pyright infers `list[str]` from both branches. Writing through `ctx.workspace.write_text` rather than redirecting in a shell keeps the write-root guard in force and removes the temporary file. The write is after the exit-code check, so a rejected edit leaves the file as it was.

- [ ] **Step 7: Register it**

In `ancalagon/worker.py`, import `EditJson` from `ancalagon.tools.artifacts.edit_json` and add to `available_tools`, next to `QueryJson`:

```python
        bound_for(EditJson(), role),
```

- [ ] **Step 8: Run the tests**

```bash
uv run --no-sync python -m pytest tests/unit/test_json_edit.py -v
```

Expected: 3 passed.

- [ ] **Step 9: Mutation-check the tests before trusting them**

A test written after the code is a hypothesis until it has failed. Break the code twice and confirm the failure lands where you claimed:

1. Move `ctx.workspace.write_text(path, out)` above the `if code != 0` check. `test_edit_json_refuses_a_path_outside_the_write_root_and_a_value_jq_rejects` must fail on `target.read_text() == "{}"`.
2. Swap the two `replace` calls in `path_of` so `~0` is unescaped first. `test_a_json_pointer_becomes_the_path_jq_indexes_with` must fail on the `/a~1b/c~0d` assertion.

Restore the code after each.

- [ ] **Step 10: Document it**

In `README.md`'s tool table, immediately after the `query_json` row:

```markdown
| `edit_json` | change one place in a JSON file in the write root, so a large answer is built across many calls |
```

- [ ] **Step 11: Verify and commit**

```bash
uv run --no-sync python -m black . && uv run --no-sync pyright && uv run --no-sync lint-imports
uv run --no-sync python -m pytest tests/unit -q && uv run --no-sync python -m pytest tests/integration -q
git add -A && git commit
```

Commit message subject: `Edit a JSON file in place instead of rewriting it`.

---

### Task 3: Submitting a pointer

An answer contract of three fields, and a terminal tool that takes it. A role using this declares `answer` as `AnswerFile` and names `submit_answer_as_file` in `tools`, so its parent collects a status, a sentence and a path instead of the whole answer.

The tool checks its own arguments and nothing else: that the path resolves inside the workspace and that a file is there. It does not look at the contents. A tool must not depend on a hook a role may not have wired, and the schema describing those contents is the hook's business. A role that wires no hook submits an unchecked file, which is the same latitude every other tool has.

**Files:**
- Create: `ancalagon/contracts/schema_guided.py`
- Create: `ancalagon/contracts/answer_status.py`
- Create: `ancalagon/contracts/answer_file.py`
- Create: `ancalagon/tools/submit/submit_answer_as_file.py`
- Create: `ancalagon/tools/submit/submitting.py`
- Modify: `ancalagon/session.py` — replace the module constant `SUBMIT` with `self.submit`
- Modify: `ancalagon/worker.py` — register the tool in `available_tools`
- Modify: `ancalagon/cli.py` — `_submit_fault` accepts either tool
- Modify: `README.md`, `docs/architecture.md`
- Test: `tests/unit/test_answer_file.py`, and extend `tests/unit/test_session_loop.py`

**Interfaces:**
- Consumes: Task 1's `ancalagon.cli._submit_fault(name: str, role: Role) -> str`.
- Produces:
  - `ancalagon.contracts.schema_guided.SchemaGuided` — `output_schema: pathlib.PurePath`. A project's input contract subclasses it.
  - `ancalagon.contracts.answer_status.AnswerStatus` — `StrEnum`, `COMPLETE = "complete"`, `PARTIAL = "partial"`.
  - `ancalagon.contracts.answer_file.AnswerFile` — `status: AnswerStatus`, `summary: str`, `path: pathlib.PurePath`.
  - `ancalagon.tools.submit.submit_answer_as_file.SubmitAnswerAsFile` — `name = "submit_answer_as_file"`, `cost = 0`, `args_model = AnswerFile`.
  - `ancalagon.tools.submit.submitting.submitting(tools: collections.abc.Sequence[str]) -> str` — the name of the terminal submit tool the role named.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_answer_file.py`:

```python
import pathlib

from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.answer_status import AnswerStatus
from ancalagon.contracts.submitted import Submitted
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import submitting
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )


def test_the_role_chooses_which_terminal_tool_it_submits_with():
    assert submitting(("read_file", "submit_answer")) == SubmitAnswer.name
    assert submitting(("read_file", "submit_answer_as_file")) == SubmitAnswerAsFile.name
    assert submitting(("submit_answer", "submit_answer_as_file")) == SubmitAnswerAsFile.name


def test_submitting_a_file_ends_the_run_and_refuses_a_file_that_is_not_there(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    answer = tmp_path / "ws" / "record.json"
    answer.write_text('{"values": []}')
    tool = SubmitAnswerAsFile()

    accepted = tool.run(
        AnswerFile(
            status=AnswerStatus.COMPLETE,
            summary="one record with no values",
            path=pathlib.PurePath(answer),
        ),
        ctx,
    )
    assert accepted.ok
    assert isinstance(accepted.summary, Submitted)
    assert accepted.summary.answer == AnswerFile(
        status=AnswerStatus.COMPLETE,
        summary="one record with no values",
        path=pathlib.PurePath(answer),
    )

    missing = tool.run(
        AnswerFile(
            status=AnswerStatus.PARTIAL,
            summary="nothing written yet",
            path=pathlib.PurePath(tmp_path / "ws" / "absent.json"),
        ),
        ctx,
    )
    assert not missing.ok
    assert "absent.json" in missing.error
```

And in `tests/unit/test_session_loop.py`, a behaviour for the session forcing the tool the role named. Add near `test_a_hook_gates_every_answer_and_prose_cannot_evade_it`:

```python
def test_the_final_turn_forces_whichever_submit_tool_the_role_named(tmp_path: pathlib.Path):
    answer = tmp_path / "ws" / "record.json"
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    answer.write_text('{"values": []}')
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = TaskSpec(
        task_id="t1",
        role=Role(
            behaviour="You answer questions.",
            answer=ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile"),
            tools=("submit_answer_as_file",),
            budget=Budget(turns=0, tool_calls=4),
        ),
        goal="Answer it.",
    )
    arguments = json.dumps(
        {"status": "complete", "summary": "one record", "path": str(answer)}
    )
    llm = FakeLLM(
        [
            Reply(
                blocks=[ToolUse(id="s1", name="submit_answer_as_file", arguments=arguments)],
                stop_reason="tool_calls",
            )
        ]
    )
    session = Session(
        spec=spec,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=llm,
        registry=Registry([bind_tool(SubmitAnswerAsFile())]),
        ctx=ctx,
        output_class=AnswerFile,
        clock=FakeClock(),
    )

    outcome = session.run()

    assert llm.forced == ["submit_answer_as_file"]
    assert [sorted(s.name for s in seen) for seen in llm.offered] == [["submit_answer_as_file"]]
    assert isinstance(outcome, Exhausted)
    assert outcome.value == AnswerFile(
        status=AnswerStatus.COMPLETE, summary="one record", path=pathlib.PurePath(answer)
    )
```

Import `AnswerFile`, `AnswerStatus` and `SubmitAnswerAsFile` at the top of the test file. `budget = { turns = 0 }` makes the first turn the forced final one, which is where the hardcoded name would break.

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run --no-sync python -m pytest tests/unit/test_answer_file.py -v
uv run --no-sync python -m pytest tests/unit/test_session_loop.py::test_the_final_turn_forces_whichever_submit_tool_the_role_named -v
```

Expected: `ModuleNotFoundError: No module named 'ancalagon.contracts.answer_file'`.

- [ ] **Step 3: The contracts**

`ancalagon/contracts/schema_guided.py`:

```python
# An input contract that names the JSON Schema the agent's answer file must satisfy.
import pathlib

import pydantic


class SchemaGuided(pydantic.BaseModel, frozen=True):
    output_schema: pathlib.PurePath
```

A project's own input contract subclasses this and adds what its role needs. It is a base class rather than a protocol for the reason `Cited` is: a subclass puts the error on the broken contract instead of on a distant annotation, and makes the implementations navigable from the base.

`ancalagon/contracts/answer_status.py`:

```python
# What an agent thinks of its own answer, which is not the same as how its run ended.
import enum


class AnswerStatus(enum.StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
```

`ancalagon/contracts/answer_file.py`:

```python
# An answer that lives in a file: what a parent learns without opening it, and where it is.
import pathlib

import pydantic

from ancalagon.contracts.answer_status import AnswerStatus


class AnswerFile(pydantic.BaseModel, frozen=True):
    status: AnswerStatus
    summary: str
    path: pathlib.PurePath
```

- [ ] **Step 4: The tool**

`ancalagon/tools/submit/submit_answer_as_file.py`:

```python
# Ends a run with a pointer to the answer on disk, for a contract too large to emit in one reply.
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class SubmitAnswerAsFile(Tool[AnswerFile]):
    name = "submit_answer_as_file"
    description = (
        "Submit your final answer as a file you have already written with write_file and "
        "edit_json. Call this exactly once, when you are done. Give the path to that file, "
        "whether the answer is complete or partial, and one sentence describing it. This "
        "does not consume your tool-call budget."
    )
    cost = 0
    args_model = AnswerFile

    def run(self, args: AnswerFile, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not ctx.workspace.is_file(path):
            return ctx.failure(self.name, f"no answer file at {path}")
        payload = Submitted(answer=args)
        written = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=written)
```

`Submitted(answer=args)` is what makes the run end: `session._outcome_of_use` reads a `Submitted` payload and returns `Completed`, or `Exhausted` on the final turn. Nothing in the session changes for that.

- [ ] **Step 5: One place decides which tool is terminal**

`ancalagon/tools/submit/submitting.py`:

```python
# Which terminal submit tool a role named; the session offers and forces that one.
import collections.abc

from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile


def submitting(tools: collections.abc.Sequence[str]) -> str:
    return SubmitAnswerAsFile.name if SubmitAnswerAsFile.name in tools else SubmitAnswer.name
```

- [ ] **Step 6: The session asks instead of assuming**

In `ancalagon/session.py`, delete the module constant `SUBMIT = "submit_answer"` and import `submitting` from `ancalagon.tools.submit.submitting`. In `__init__`, alongside the other assignments:

```python
        self.submit = submitting(spec.role.tools)
```

Then replace all three uses of `SUBMIT`:

```python
    def _declarations(
        self, final: bool, outstanding: collections.abc.Sequence[int]
    ) -> list[ToolSchema]:
        if final:
            return [self.registry.get(self.submit).declaration]
        uncollected = self.children.uncollected()
        excluded: set[str] = ({IDLE} if not outstanding else set[str]()) | (
            {self.submit} if outstanding or uncollected else set[str]()
        )
```

and in `run()`:

```python
            reply = self._complete(declarations, force_tool=self.submit if final else "")
```

Existing sessions built with `tools=()` get `"submit_answer"` from `submitting`, so nothing else in the test suite changes.

Three prompt strings also name the tool in prose and would otherwise tell an agent to call something it has not been given. `FINAL_INSTRUCTION` and `CONTINUE_INSTRUCTION` become methods so they can interpolate `self.submit`:

```python
    def _final_instruction(self) -> str:
        return (
            f"Your budget is exhausted. Answer now from what you already know, "
            f"using the {self.submit} tool. No other tools are available."
        )

    def _continue_instruction(self) -> str:
        return (
            f"Answers are only accepted through the {self.submit} tool. Keep working, and "
            f"call it when you have your answer."
        )
```

Delete both module constants and call the methods from `_prepare_final_turn` and `_uncalled`. In `_system`, replace the two literal mentions of `submit_answer` with `{self.submit}`.

The schema line in `_system` needs care. It reads `Your answer must match this schema: {self.output_class.model_json_schema()}`, and for a `submit_answer_as_file` role `output_class` is `AnswerFile` — so the model is told to match a three-field pointer, which is true and is what it submits. Leave it. The schema of the *file* is the hook's business and reaches the model through the refusal, not the system prompt.

Two assertions in `tests/unit/test_session_loop.py` match the old constants as text — the regression test added in `9fe7c09` asserts `"Answers are only accepted through the submit_answer tool" in transcript`. The interpolated string is identical for a `submit_answer` role, so those assertions keep passing. If one fails, the interpolation changed the wording; fix the wording, not the assertion.

Run `uv run --no-sync lint-imports` at this point specifically. `ancalagon.session` already imports from `ancalagon.tools.registry`; if a contract forbids it importing `ancalagon.tools.submit`, stop and report rather than editing `pyproject.toml` — which package may import which is a decision, not a detail.

- [ ] **Step 7: Register the tool and widen the config check**

In `ancalagon/worker.py`, import `SubmitAnswerAsFile` and add to `available_tools` after `SubmitAnswer`:

```python
        bound_for(SubmitAnswerAsFile(output_class), role),
```

Careful — `SubmitAnswerAsFile` takes no constructor argument, unlike `SubmitAnswer`. The line is:

```python
        bound_for(SubmitAnswerAsFile(), role),
```

In `ancalagon/cli.py`, `_submit_fault` accepts either:

```python
SUBMITTING = (SubmitAnswer.name, SubmitAnswerAsFile.name)


def _submit_fault(name: str, role: Role) -> str:
    if role.run is not NO_RUN or set(role.tools) & set(SUBMITTING):
        return ""
    return (
        f"[roles.{name}] tools: a role that runs a session must name one of "
        f"{sorted(SUBMITTING)}; named: {sorted(role.tools)}"
    )
```

Update Task 1's test assertion if it matched the old message text — it asserts `"submit_answer" in str(...)`, which still holds.

- [ ] **Step 8: Run the tests**

```bash
uv run --no-sync python -m pytest tests/unit -q
uv run --no-sync python -m pytest tests/integration -q
```

- [ ] **Step 9: Mutation-check**

1. Hardcode `"submit_answer"` back into `_declarations`'s `final` branch. `test_the_final_turn_forces_whichever_submit_tool_the_role_named` must fail with `KeyError: 'unknown tool submit_answer'`.
2. Delete the `is_file` check in `SubmitAnswerAsFile.run`. `test_submitting_a_file_ends_the_run_and_refuses_a_file_that_is_not_there` must fail on `assert not missing.ok`.

- [ ] **Step 10: Document it**

`README.md` tool table, after the `submit_answer` row:

```markdown
| `submit_answer_as_file` | the final answer as a file you already wrote, free — for a contract too large to emit in one reply |
```

Then, after the paragraph about a reply that calls no tool, add a short section explaining the two terminal tools: `submit_answer` carries the answer in its arguments, so its parameter schema *is* the answer contract and the whole answer must fit in one completion; `submit_answer_as_file` carries a status, a sentence and a path, so the answer is built on disk across many `edit_json` calls and a parent collecting it pays three fields instead of the whole record. A role names one or the other. Show the TOML:

```toml
[roles.record_analyst]
answer = { module = "ancalagon.contracts.answer_file", name = "AnswerFile" }
tools = ["read_file", "write_file", "edit_json", "submit_answer_as_file"]
```

`docs/architecture.md` — in the section on the loop, note that `_declarations` and `force_tool` use the name `submitting(role.tools)` returns rather than a constant, so the role's choice of terminal tool reaches the forced final turn. In the section on contracts, say that `AnswerFile` is an answer contract like any other and that the file it names is outside Pydantic's reach on purpose — the structure is described by a JSON Schema because it is never a Python value.

- [ ] **Step 11: Verify and commit**

```bash
uv run --no-sync python -m black . && uv run --no-sync pyright && uv run --no-sync lint-imports
uv run --no-sync python -m pytest tests/unit -q && uv run --no-sync python -m pytest tests/integration -q
git add -A && git commit
```

Commit message subject: `Answer with a file when the answer will not fit in a reply`.

---

### Task 4: `adheres_to_schema`

A `before` hook on `submit_answer_as_file` that reads the answer file and checks it against the JSON Schema the task's input named. Declared per role, like every other hook, and gated at build time by `accepts` because its first parameter is the tool's own args model.

**One deliberate exception to a guardrail, and it is the whole point of the feature.** `CLAUDE.md` bans intermediate JSON representations in Python: a value read from JSON becomes a Pydantic model immediately. Here there is no model to become — the structure is described by a schema file precisely because it is too large to be a Python class, and the spec rejected making JSON Schema the contract of record for everything else. So `json.loads` appears exactly twice, both inside this function, and neither value is annotated, returned, or passed anywhere. If a later change wants to move those values out of this function, that change needs a Pydantic model and this exception should be revisited rather than widened.

**Files:**
- Create: `ancalagon/tools/submit/adheres_to_schema.py`
- Modify: `pyproject.toml` — add `jsonschema` to `dependencies`
- Modify: `README.md`, `docs/architecture.md` — the hook chain
- Test: `tests/unit/test_answer_file.py` (extend)

**Interfaces:**
- Consumes: Task 3's `AnswerFile`, `AnswerStatus`, `SchemaGuided`, `SubmitAnswerAsFile`.
- Produces: `ancalagon.tools.submit.adheres_to_schema.adheres_to_schema(args: AnswerFile, ctx: ToolContext) -> Reviewed`.

- [ ] **Step 1: Declare the dependency**

`pyproject.toml`, in `dependencies`:

```toml
    "jsonschema>=4.26",
```

Then `uv sync`. It is already resolved in the lock as a transitive dependency, so this only makes the direct use honest.

- [ ] **Step 2: Write the failing test**

Extend `tests/unit/test_answer_file.py`:

```python
def test_the_schema_hook_accepts_a_conforming_file_and_names_every_fault(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    schema = write_root / "record.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name", "values"],
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "integer"}},
                },
            }
        )
    )
    answer = write_root / "record.json"
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
        input=Guided(output_schema=pathlib.PurePath(schema)),
    )
    submitted = AnswerFile(
        status=AnswerStatus.COMPLETE, summary="a record", path=pathlib.PurePath(answer)
    )

    answer.write_text(json.dumps({"name": "a", "values": [1, 2]}))
    assert adheres_to_schema(submitted, ctx) == Accepted(value=submitted)

    answer.write_text(json.dumps({"values": [1, "two"]}))
    refusal = adheres_to_schema(submitted, ctx)
    assert isinstance(refusal, Refused)
    assert "/values/1" in refusal.reason
    assert "'name' is a required property" in refusal.reason

    unguided = ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )
    assert isinstance(adheres_to_schema(submitted, unguided), Refused)
```

At the top of the file add a `Guided` contract for the test to use, since `SchemaGuided` is a base a project subclasses:

```python
class Guided(SchemaGuided, frozen=True):
    pass
```

and import `Accepted`, `Refused`, `SchemaGuided` and `adheres_to_schema`. The refusal must name **every** fault, not the first: the agent pays a turn per refusal, so a file with fifteen faults corrected one at a time would spend its budget on round trips. That is the same reason `evidence_resolves` aggregates.

- [ ] **Step 3: Run it and watch it fail**

```bash
uv run --no-sync python -m pytest tests/unit/test_answer_file.py -v
```

Expected: `ModuleNotFoundError: No module named 'ancalagon.tools.submit.adheres_to_schema'`.

- [ ] **Step 4: The hook**

`ancalagon/tools/submit/adheres_to_schema.py`:

```python
# Refuses an answer file that does not satisfy the JSON Schema the task's input named.
import json

import jsonschema

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.schema_guided import SchemaGuided
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _fault(error: jsonschema.ValidationError) -> str:
    where = "/" + "/".join(str(part) for part in error.absolute_path)
    return f"{where}: {error.message}"


def adheres_to_schema(args: AnswerFile, ctx: ToolContext) -> Reviewed:
    if not isinstance(ctx.input, SchemaGuided):
        return Refused(
            reason=f"this role's input contract does not name an output schema: {type(ctx.input).__name__}"
        )
    try:
        schema_path = ctx.workspace.resolve_read(ctx.input.output_schema)
        answer_path = ctx.workspace.resolve_write(args.path)
    except ScopeError as exc:
        return Refused(reason=str(exc))
    validator = jsonschema.Draft202012Validator(json.loads(ctx.workspace.read_text(schema_path)))
    faults = [_fault(error) for error in validator.iter_errors(json.loads(ctx.workspace.read_text(answer_path)))]
    if faults:
        return Refused(reason=f"{answer_path} does not match {schema_path}:\n" + "\n".join(faults))
    return Accepted(value=args)
```

Black will wrap those long lines; run it rather than hand-wrapping. Confirm the exact class names in `ancalagon/contracts/` — `Accepted` and `Refused` are what `evidence_resolves` returns, so copy the imports from `ancalagon/tools/submit/evidence_resolves.py` rather than guessing.

`isinstance(ctx.input, SchemaGuided)` is not a defensive guard: `ctx.input` is typed `pydantic.BaseModel` because it is whatever the role declared, and this hook needs the one field only a `SchemaGuided` has. It refuses plainly rather than raising, so the model reads the misconfiguration in its own transcript while the run continues.

- [ ] **Step 5: Run it and watch it pass**

```bash
uv run --no-sync python -m pytest tests/unit/test_answer_file.py -v
```

- [ ] **Step 6: Prove the build-time gate catches a wrongly shaped hook**

`accepts` reads the declared type of a hook's first parameter and requires `issubclass(args_model, declared)`. Confirm it: temporarily attach `adheres_to_schema` to `read_file` in a role's `[roles.x.before]` in a scratch config and run `uv run ancalagon check --config <that file>`. It must exit non-zero naming the role, not fail mid-run. Delete the scratch config afterwards. Find the exact `check` subcommand name in `ancalagon/cli.py` before running it.

- [ ] **Step 7: Document the chain**

`README.md`, in the hooks section after `evidence_resolves`: `adheres_to_schema` attaches to `submit_answer_as_file` and checks the file against the schema the role's input named, reporting every fault at once. Show the declaration:

```toml
[roles.record_analyst.before]
submit_answer_as_file = [
  { module = "ancalagon.tools.submit.adheres_to_schema", name = "adheres_to_schema" },
]
```

Say that hooks compose in order, so a role can follow this one with its own check of a property the schema cannot express, and that a role wiring no hook submits an unchecked file — the check is opt-in by declaration like every other hook.

`docs/architecture.md` — in the hooks section, record the one place a parsed JSON value exists in this codebase and why: the structure the schema describes is never a Python value, which is the entire reason this route exists.

- [ ] **Step 8: Verify and commit**

```bash
uv run --no-sync python -m black . && uv run --no-sync pyright && uv run --no-sync lint-imports
uv run --no-sync python -m pytest tests/unit -q && uv run --no-sync python -m pytest tests/integration -q
git add -A && git commit
```

Commit message subject: `Check an answer file against the schema its task named`.

---

## After the four tasks

The feature is usable but has never run against a real model. Propose to the user an integration test in the style of `tests/integration/test_scripted_hooks.py`: a scripted `FakeLLM` role that writes `{}` with `write_file`, appends two records with `edit_json`, submits with `submit_answer_as_file`, and has `adheres_to_schema` wired — asserting the run ends `Completed` with an `AnswerFile` whose path holds both records, and that a role submitting a file with a missing required property is refused and told which pointer failed. That test is the first thing that exercises all four tasks together, and it belongs in its own commit.

Do not build it without asking. The user's standing constraint is one logical unit per commit and no work beyond what was asked.

## Self-review

**Spec coverage.** `edit_json` with `JsonOp`/`EditArgs` and a pointer-to-jq-path pure function: Task 2. `SchemaGuided`: Task 3, Step 3. `AnswerStatus`/`AnswerFile`/`SubmitAnswerAsFile` and registration: Task 3. `adheres_to_schema` plus the `jsonschema` dependency: Task 4. README and `architecture.md` updates: in the task whose behaviour they describe. The spec's rejected alternatives need no task. The spec did **not** cover two things this plan adds, both forced by the "one route in" decision the user made after the spec was written: dropping the unconditional `submit_answer` injection (Task 1) and `submitting()` replacing the hardcoded `SUBMIT` constant in the session (Task 3, Steps 5–6). The spec is immutable, so they are recorded here. A third thing neither the spec nor the user's instruction mentioned turned up while checking the code: `session.py` names `submit_answer` in three prompt strings as well as three lookups, so Task 3 Step 6 covers both.

**Placeholders.** None. Every code step carries the code; every doc step says what the sentence must assert rather than "update the docs".

**Type consistency.** `JsonEditArgs` is used under that name in Tasks 2's tool, tests and interfaces block — never `EditArgs`, which already exists for `edit_file`. `path_of` returns `JsonPath` in both its definition and its call site. `submitting` takes `collections.abc.Sequence[str]` and is called with `spec.role.tools`, which is `tuple[str, ...]`. `_submit_fault(name, role)` has the same signature in Task 1 and Task 3. `SubmitAnswerAsFile()` takes no constructor argument, which Task 3 Step 7 flags explicitly because the line above it in `available_tools` does take one.
