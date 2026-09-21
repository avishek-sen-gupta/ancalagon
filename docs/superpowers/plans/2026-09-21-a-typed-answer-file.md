# A Typed Answer File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `submit_answer_as_file` is constructed with the Pydantic class its file must hold, and refuses a file that does not validate into it.

**Architecture:** A role names the content class in a new `answer_file` field. `session_for` and `check_contracts` resolve it and hand it to `build_registry`, which constructs `SubmitAnswerAsFile(content_class)`. The tool reads the file and calls `model_validate_json`; a `ValidationError` is a tool failure listing every fault. The JSON Schema route (`SchemaGuided`, `adheres_to_schema`, `jsonschema`) is then deleted.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-09-21-a-typed-answer-file-design.md`

## Global Constraints

- Pyright strict, zero errors. No `Any`, no `object`, no bare generics, no JSON-blob types.
- No comments except a one-line header per module or class.
- Frozen Pydantic models and dataclasses. One class per file.
- No `None` defaults; null objects instead (`NO_ANSWER_FILE`, following `NO_RUN`).
- No mocks; real file system under `tmp_path`, fakes by injection.
- Few tests, each covering a whole behaviour; extend existing behaviour tests where the behaviour already has one.
- Never modify `docs/superpowers/specs/` or `docs/superpowers/plans/` beyond this plan.
- No names from codebases under analysis in anything tracked; use `com.example.*`, `Record`, `Foo`.
- Verify: `uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports`. Run the whole integration suite, not one file.

---

### Task 1: Type the answer file

One commit: the field, the tool, the startup checks, the research migration and the docs. `research.toml` fails startup without its migration, so it cannot ride separately.

**Files:**
- Create: `ancalagon/contracts/no_answer_file.py`
- Create: `ancalagon/research/finding.py`, `ancalagon/research/findings.py`, `ancalagon/research/claim.py`, `ancalagon/research/undetermined.py`, `ancalagon/research/report.py`
- Modify: `ancalagon/contracts/role.py`
- Modify: `ancalagon/config/raw_role.py`
- Modify: `ancalagon/config/load.py` (`_role`)
- Modify: `ancalagon/tools/submit/submit_answer_as_file.py`
- Modify: `ancalagon/session_for.py` (`available_tools`, `build_registry`, `session_for`)
- Modify: `ancalagon/check_contracts.py`
- Modify: `research.toml`
- Modify: `README.md`, `docs/architecture.md`, `ancalagon.example.toml`
- Test: `tests/unit/test_answer_file.py`, `tests/unit/test_config_load.py`, `tests/integration/test_answer_as_file.py`
- Update callers of `build_registry` / `SubmitAnswerAsFile()`: `tests/unit/test_watch.py:223`, `tests/unit/test_hooks.py:202`, `tests/unit/test_tools.py:353,365,381,413,439`, `tests/unit/test_session_loop.py:821,863`

**Interfaces:**
- Produces: `ancalagon.contracts.no_answer_file.NoAnswerFile` (fieldless frozen model) and `NO_ANSWER_FILE: ClassRef`.
- Produces: `Role.answer_file: ClassRef = NO_ANSWER_FILE`.
- Produces: `SubmitAnswerAsFile(content_class: type[pydantic.BaseModel])`.
- Produces: `build_registry(..., output_class: type[pydantic.BaseModel], answer_file_class: type[pydantic.BaseModel], clock, fs, web, bus)` and `available_tools(..., output_class, answer_file_class, clock, fs, web, bus)` — a new keyword parameter directly after `output_class`.

- [ ] **Step 1: Write the failing tool test**

In `tests/unit/test_answer_file.py`, add `import pydantic` and a content model after `ANSWER_FILE`:

```python
class Record(pydantic.BaseModel, frozen=True):
    name: str
    values: tuple[int, ...]
```

Replace `test_submitting_a_file_ends_the_run_and_refuses_a_file_that_is_not_there` with:

```python
def test_submitting_a_file_validates_it_into_the_role_s_class_and_refuses_what_does_not_fit(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    answer = tmp_path / "ws" / "record.json"
    tool = SubmitAnswerAsFile(Record)
    submitted = AnswerFile(
        status=AnswerStatus.COMPLETE, summary="a record", path=pathlib.PurePath(answer)
    )

    assert json.dumps(Record.model_json_schema()) in tool.description

    answer.write_text(json.dumps({"name": "a", "values": [1, 2]}))
    accepted = tool.run(submitted, ctx)
    assert accepted.ok
    assert isinstance(accepted.summary, Submitted)
    assert accepted.summary.answer == submitted

    answer.write_text(json.dumps({"values": [1, "two"]}))
    mismatched = tool.run(submitted, ctx)
    assert not mismatched.ok
    assert mismatched.error == (
        f"{answer} does not match Record:\n"
        "/name: Field required\n"
        "/values/1: Input should be a valid integer, unable to parse string as an integer"
    )

    answer.write_text("{oops")
    unparsable = tool.run(submitted, ctx)
    assert not unparsable.ok
    assert unparsable.error.startswith(f"{answer} does not match Record:\n/: Invalid JSON: ")

    missing = tool.run(
        AnswerFile(
            status=AnswerStatus.PARTIAL,
            summary="nothing written yet",
            path=pathlib.PurePath(tmp_path / "ws" / "absent.json"),
        ),
        ctx,
    )
    assert not missing.ok
    assert missing.error == f"no answer file at {tmp_path / 'ws' / 'absent.json'}"
```

In `test_the_role_chooses_which_terminal_tool_it_submits_with`, give the role `answer_file=ClassRef(module=__name__, name="Record")` and pass `answer_file_class=Record` to `build_registry` after `output_class=AnswerFile`.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_answer_file.py -v`
Expected: FAIL — `SubmitAnswerAsFile()` takes no arguments / `build_registry` has no `answer_file_class`.

- [ ] **Step 3: Add the null object and the role field**

`ancalagon/contracts/no_answer_file.py`:

```python
# The class a role's answer file holds when the role submits no file: there is not one.
import pydantic

from ancalagon.contracts.class_ref import ClassRef


class NoAnswerFile(pydantic.BaseModel, frozen=True):
    pass


NO_ANSWER_FILE = ClassRef(module="ancalagon.contracts.no_answer_file", name="NoAnswerFile")
```

In `ancalagon/contracts/role.py` import `NO_ANSWER_FILE` and add after `answer`:

```python
    answer_file: ClassRef = NO_ANSWER_FILE
```

In `ancalagon/config/raw_role.py` add after `answer`:

```python
    answer_file: RawClassRef = RawClassRef()
```

In `ancalagon/config/load.py` import `NO_ANSWER_FILE` and pass, in `_role`'s `Role(...)` after `answer=produced`:

```python
        answer_file=_class_ref(raw.answer_file) if raw.answer_file.module else NO_ANSWER_FILE,
```

- [ ] **Step 4: Make the tool validate**

Replace `ancalagon/tools/submit/submit_answer_as_file.py` with:

```python
# Ends a run with a pointer to the answer on disk, once the file validates into the role's class.
import json

import pydantic
import pydantic_core

from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _fault(error: pydantic_core.ErrorDetails) -> str:
    return "/" + "/".join(str(part) for part in error["loc"]) + f": {error['msg']}"


class SubmitAnswerAsFile(Tool[AnswerFile]):
    name = "submit_answer_as_file"
    cost = 0
    args_model = AnswerFile

    def __init__(self, content_class: type[pydantic.BaseModel]):
        self.content_class = content_class
        self.description = (
            "Submit your final answer as a file you have already written with write_file and "
            "edit_json. Call this exactly once, when you are done. Give the path to that file, "
            "whether the answer is complete or partial, and one sentence describing it. The "
            "file must be JSON matching this schema, and is refused with every fault listed if "
            f"it does not: {json.dumps(content_class.model_json_schema())}. This does not "
            "consume your tool-call budget."
        )

    def run(self, args: AnswerFile, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not ctx.workspace.is_file(path):
            return ctx.failure(self.name, f"no answer file at {path}")
        try:
            self.content_class.model_validate_json(ctx.workspace.read_text(path))
        except pydantic.ValidationError as exc:
            faults = "\n".join(_fault(error) for error in exc.errors())
            return ctx.failure(
                self.name, f"{path} does not match {self.content_class.__name__}:\n{faults}"
            )
        payload = Submitted(answer=args)
        written = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=written)
```

If Pyright objects to `description` being set on the instance, compare with `ancalagon/tools/submit/submit_answer.py`, which does the same.

- [ ] **Step 5: Thread the class through the registry**

In `ancalagon/session_for.py`:
- `available_tools` gains `answer_file_class: type[pydantic.BaseModel],` after `output_class`, and builds `bound_for(SubmitAnswerAsFile(answer_file_class), role)`.
- `build_registry` gains the same parameter after `output_class` and passes `answer_file_class=answer_file_class` into `available_tools` (positionally after `output_class`, matching the existing call).
- `session_for` passes `answer_file_class=resolve_class(spec.role.answer_file)` to `build_registry` after `output_class=output_class`.

In `ancalagon/check_contracts.py`, `_hook_fault`'s `build_registry` call passes `answer_file_class=resolve_class(role.answer_file)` after `output_class`.

Update every other caller listed under **Files**. Each passes `answer_file_class=NoAnswerFile` (import from `ancalagon.contracts.no_answer_file`), except:
- `tests/unit/test_session_loop.py:821` → `bind_tool(SubmitAnswerAsFile(Values))`, and `:863` → `answer_file_class=Values`, where `Values` is a frozen model with `values: tuple[int, ...]` defined in that test module. Both answer files there already contain `{"values": []}`. Give `role_both` `answer_file=ClassRef(module=__name__, name="Values")`.

Find the callers structurally rather than trusting the list:

```bash
ast-grep --lang python -p 'build_registry($$$)' tests ancalagon
ast-grep --lang python -p 'SubmitAnswerAsFile($$$)' tests ancalagon
```

- [ ] **Step 6: Run the tool tests**

Run: `uv run pytest tests/unit/test_answer_file.py tests/unit/test_session_loop.py tests/unit/test_tools.py tests/unit/test_hooks.py tests/unit/test_watch.py -v`
Expected: PASS.

- [ ] **Step 7: Write the failing startup test**

In `tests/unit/test_config_load.py`, import `AnswerFile`'s ref and `NO_ANSWER_FILE`:

```python
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
```

Extend `test_roles_load_with_their_contracts_and_prose_is_the_absent_default`: add `answer_file = { module = "shapekit.shapes", name = "Component" }` to `[roles.analyst]`, and assert:

```python
    assert roles["analyst"].answer_file == ClassRef(module="shapekit.shapes", name="Component")
    assert roles["scout"].answer_file == NO_ANSWER_FILE
```

Extend `test_a_session_role_must_name_a_submit_tool` after the `wrong_answer` block:

```python
    answer_file_ref = ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile")
    content = ClassRef(module="ancalagon.contracts.free_text", name="FreeText")
    untyped = filer.model_copy(update={"answer": answer_file_ref})
    with pytest.raises(ValueError) as no_content:
        check_contracts(config.model_copy(update={"roles": {"filer": untyped}}), RealFileSystem())
    assert str(no_content.value) == (
        "[roles.filer] names submit_answer_as_file, so it must declare answer_file: "
        "the class its answer file holds"
    )

    stray = Role(
        behaviour="You answer.",
        answer_file=content,
        tools=("submit_answer",),
        budget=finite_budget(1, 1),
    )
    with pytest.raises(ValueError) as unchecked:
        check_contracts(config.model_copy(update={"roles": {"stray": stray}}), RealFileSystem())
    assert str(unchecked.value) == (
        "[roles.stray] declares answer_file as FreeText in ancalagon.contracts.free_text, "
        "but does not name submit_answer_as_file, so nothing checks it"
    )

    unloadable = untyped.model_copy(
        update={"answer_file": ClassRef(module="ancalagon.contracts.free_text", name="Missing")}
    )
    with pytest.raises(ValueError) as unresolved:
        check_contracts(
            config.model_copy(update={"roles": {"filer": unloadable}}), RealFileSystem()
        )
    assert str(unresolved.value) == (
        "[roles.filer] answer_file names Missing in ancalagon.contracts.free_text, which "
        "cannot be loaded: AttributeError: module 'ancalagon.contracts.free_text' has no "
        "attribute 'Missing'"
    )

    typed = untyped.model_copy(update={"answer_file": content})
    check_contracts(config.model_copy(update={"roles": {"filer": typed}}), RealFileSystem())
```

`check_contracts` joins faults with newlines and each block has one role with one fault, so the message is that fault alone.

- [ ] **Step 8: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_config_load.py -v`
Expected: FAIL — no fault for the untyped or stray role; the unloadable one fails inside `build_registry` with a different message.

- [ ] **Step 9: Add the startup faults**

In `ancalagon/check_contracts.py`:
- import `NO_ANSWER_FILE`;
- in `check_contracts`, the first comprehension iterates `(("input", role.input), ("answer", role.answer), ("answer_file", role.answer_file))`;
- add, after `_answer_file_fault`:

```python
def _content_fault(name: str, role: Role) -> str:
    names_tool = SubmitAnswerAsFile.name in role.tools
    declares = role.answer_file != NO_ANSWER_FILE
    if names_tool == declares:
        return ""
    if names_tool:
        return (
            f"[roles.{name}] names {SubmitAnswerAsFile.name}, so it must declare answer_file: "
            "the class its answer file holds"
        )
    return (
        f"[roles.{name}] declares answer_file as {role.answer_file.name} in "
        f"{role.answer_file.module}, but does not name {SubmitAnswerAsFile.name}, so nothing "
        "checks it"
    )
```

- and chain it in the `or` sequence directly after the `_answer_file_fault` comprehension, in the same shape.

- [ ] **Step 10: Run the startup tests**

Run: `uv run pytest tests/unit/test_config_load.py -v`
Expected: PASS.

- [ ] **Step 11: Move the integration test to a content class**

In `tests/integration/test_answer_as_file.py`:
- delete `SCHEMA`;
- add a module written into the config's directory, which `load_config` puts on the path:

```python
RECORD = """
import pydantic


class Record(pydantic.BaseModel, frozen=True):
    name: str
    values: tuple[int, ...]
"""
```

- in `CONFIG`, delete the `input = ...` line and the whole `[roles.root.before]` table, and add after `answer`:

```
answer_file = {{ module = "filedkit.record", name = "Record" }}
```

- in `CONFIG`'s `[run]`, set `input_file = ""` and drop the `{input_file}` placeholder;
- `_config` writes the package instead of the schema and input file:

```python
def _config(tmp_path: pathlib.Path, write_root: pathlib.Path) -> pathlib.Path:
    write_root.mkdir(parents=True, exist_ok=True)
    package = tmp_path / "filedkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "record.py").write_text(RECORD)
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(GOAL)
    config = tmp_path / "ancalagon.toml"
    config.write_text(CONFIG.format(write_root=write_root, goal_file=goal_file))
    return config
```

- rename the test to `test_an_agent_builds_its_answer_in_a_file_and_submitting_refuses_it_until_it_fits`;
- the last assertion becomes `assert "/values: Field required" in said`.

Run: `uv run pytest tests/integration/test_answer_as_file.py -v`
Expected: PASS, with the same script, the same `called` list and the same `spent`.

- [ ] **Step 12: Add the research models**

`ancalagon/research/finding.py`:

```python
# One thing a researcher read about, and the page it was read on.
import pydantic


class Finding(pydantic.BaseModel, frozen=True):
    subject: str
    behaviour: str
    enforcement: str
    requirements: str
    url: str
    verified: bool
```

`ancalagon/research/findings.py`:

```python
# What one researcher found in its area.
import pydantic

from ancalagon.research.finding import Finding


class Findings(pydantic.BaseModel, frozen=True):
    area: str
    entries: tuple[Finding, ...]
```

`ancalagon/research/claim.py`:

```python
# A statement in a report, with the pages that support it.
import pydantic


class Claim(pydantic.BaseModel, frozen=True):
    statement: str
    urls: tuple[str, ...]
    verified: bool
```

`ancalagon/research/undetermined.py`:

```python
# A question a report could not settle, and why.
import pydantic


class Undetermined(pydantic.BaseModel, frozen=True):
    question: str
    reason: str
```

`ancalagon/research/report.py`:

```python
# The survey the research root puts together from its researchers' findings.
import pydantic

from ancalagon.research.claim import Claim
from ancalagon.research.undetermined import Undetermined


class Report(pydantic.BaseModel, frozen=True):
    differences: tuple[Claim, ...]
    claims: tuple[Claim, ...]
    undetermined: tuple[Undetermined, ...]
```

- [ ] **Step 13: Write the failing research config test**

In `tests/unit/test_config_load.py`, after `test_the_example_config_this_repo_ships_satisfies_its_own_contracts`:

```python
def test_the_research_config_this_repo_ships_types_every_answer_file():
    path = pathlib.Path(__file__).parents[2] / "research.toml"
    config = load_config(pathlib.PurePath(path), RealFileSystem())

    check_contracts(config, RealFileSystem())

    assert {name: role.answer_file for name, role in config.roles.items()} == {
        "root": ClassRef(module="ancalagon.research.report", name="Report"),
        "researcher": ClassRef(module="ancalagon.research.findings", name="Findings"),
    }
```

Run: `uv run pytest tests/unit/test_config_load.py::test_the_research_config_this_repo_ships_types_every_answer_file -v`
Expected: FAIL — `[roles.root] names submit_answer_as_file, so it must declare answer_file`.

- [ ] **Step 14: Migrate `research.toml`**

In `[roles.root]`:
- "tell it to write its findings to its own file under the write root" → "tell it to write its findings to its own JSON file under the write root";
- replace everything from "Then wait:" to the closing `"""` with:

```
Then wait: call check_task until all three have finished, and collect each one. Each returns
a path to a JSON file of findings it wrote. Read those three files.

Write one report that puts the three together, at report.json in the write root. Create it
with write_file as {"differences": [], "claims": [], "undetermined": []} and add each entry
with edit_json append. The schema is in submit_answer_as_file's description. It must:
- in differences, say where the approaches genuinely differ, not just what each one is
- in claims, keep every URL the researchers cited, attached to the claim it supports
- carry forward anything a researcher marked unverified, with verified false
- in undetermined, name what could not be determined and why

Then call submit_answer_as_file with the path to report.json.
```

- add `"edit_json",` to its tools after `"write_file",`;
- add `answer_file = { module = "ancalagon.research.report", name = "Report" }` after its `answer` line.

In `[roles.researcher]`:
- "and write what you find to a file" → "and write what you find to a JSON file";
- step 3 becomes:

```
3. Record your findings as you go, so a page you read is recorded before you move on. Create
   your file with write_file as {"area": "<your area>", "entries": []} and add each finding
   with edit_json append to /entries. Do not hold everything until the end.
```

- "Your file must contain, for each thing you describe: ... Mark anything you could not source as unverified." becomes:

```
Each entry states what the thing is, what it does, how its enforcement or validation actually
works, what it requires of the model or the API, and the URL you read it on. An entry you
could not source has verified false and an empty url. The schema is in
submit_answer_as_file's description.
```

- add `"edit_json",` to its tools after `"write_file",`;
- add `answer_file = { module = "ancalagon.research.findings", name = "Findings" }` after its `answer` line.

Run: `uv run pytest tests/unit/test_config_load.py -v`
Expected: PASS.

- [ ] **Step 15: Update the living docs**

`README.md`:
- line 213, the mermaid node: `submit_answer_as_file takes AnswerFile and the answer class must be it` → `submit_answer_as_file takes AnswerFile and the answer class must be it;<br/>the file must validate into answer_file`.
- "Two ways to submit": add `answer_file = { module = "example.contracts.record", name = "Record" }` to the toml block after `answer`, and after the paragraph that ends "rejects one that declares something else." insert:

```
`answer_file` names the class the file holds. The tool's description shows the model that
class's schema, and submitting reads the file and validates it into the class: a file that does
not fit is refused with every fault listed, `/values/1: Input should be a valid integer`, and the
agent fixes it and submits again. A role naming `submit_answer_as_file` must declare
`answer_file`, and a role declaring it without the tool is rejected at startup, since nothing
would check it.
```

`docs/architecture.md`: replace the first four sentences of the paragraph beginning "`AnswerFile` is an answer contract like any other", ending "the parent decides what to do with them.", with:

```
`AnswerFile` is an answer contract like any other: a Pydantic model assigned to `role.answer`.
The file it names holds a second contract, `role.answer_file`, which `session_for` resolves and
hands to `SubmitAnswerAsFile` at construction, exactly as `SubmitAnswer` receives its output
class. Submitting reads the file and calls `model_validate_json`; invalid JSON and a structural
mismatch both arrive as a `ValidationError`, rendered one fault per line and returned as a tool
failure the agent can retry. The validated instance is not carried upward: the file is the
answer, and the harness ships the three pointer fields (`status`, `summary`, `path`) to the
parent.
```

Leave the sentences about `adheres_to_schema` for Task 2.

`ancalagon.example.toml`:
- "Optional: input, answer, run, before, after." → "Optional: input, answer, answer_file, run, before, after.";
- after the paragraph "A role that runs a session must name submit_answer or submit_answer_as_file ... does not enable it." add:

```
# A role that names submit_answer_as_file must set answer to AnswerFile and answer_file to the
# class its file holds, as { module = "...", name = "..." }. Submitting validates the file into
# that class and refuses it, listing every fault, until it fits.
```

- [ ] **Step 16: Self-review and verify**

Scan the diff for comments, `None` checks, weak assertions, and any leftover `SubmitAnswerAsFile()` with no argument:

```bash
rg -n 'SubmitAnswerAsFile\(\)' ancalagon tests
```

Expected: no matches. Then:

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

Expected: all pass.

Mutation-check: delete the `model_validate_json` call and confirm `test_submitting_a_file_validates_it_into_the_role_s_class_and_refuses_what_does_not_fit` and the integration test fail; restore. Swap the `_content_fault` branches and confirm the startup test fails; restore.

- [ ] **Step 17: Commit**

```bash
git add ancalagon research.toml README.md docs/architecture.md ancalagon.example.toml tests
git commit -m "Validate an answer file into the class its role names

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Remove the JSON Schema route

**Files:**
- Delete: `ancalagon/contracts/schema_guided.py`, `ancalagon/tools/submit/adheres_to_schema.py`
- Modify: `tests/unit/test_answer_file.py`
- Modify: `pyproject.toml`, `uv.lock`
- Modify: `README.md`, `docs/architecture.md`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: nothing; only removal.

- [ ] **Step 1: Delete the hook's test**

In `tests/unit/test_answer_file.py` delete `test_the_schema_hook_accepts_a_conforming_file_names_every_fault_and_refuses_what_it_cannot_read`, the `Guided` class, and the imports only it used: `Accepted`, `Refused`, `SchemaGuided`, `adheres_to_schema`.

- [ ] **Step 2: Delete the code and the dependency**

```bash
git rm ancalagon/contracts/schema_guided.py ancalagon/tools/submit/adheres_to_schema.py
uv remove jsonschema
```

- [ ] **Step 3: Confirm nothing refers to the old shape**

```bash
rg -n 'schema_guided|SchemaGuided|adheres_to_schema|jsonschema|output_schema' --glob '!docs/superpowers/**' --glob '!uv.lock' .
```

Expected: matches only in `README.md` and `docs/architecture.md`, handled in the next step.

- [ ] **Step 4: Update the living docs**

`README.md`: delete the section that begins "A role whose input contract inherits `ancalagon.contracts.schema_guided.SchemaGuided`" through "declaration like every other hook." — the paragraph, its toml block and the paragraph after it.

`docs/architecture.md`: delete the sentences from "A hook that validates the file's contents runs before `submit_answer_as_file`" through "…builds the subtask.", and the whole following paragraph beginning "A hook runs inside the tool call, so anything it raises ends the whole run as `Failed`" through "…which the agent can report."

Re-run the Step 3 search. Expected: no matches.

- [ ] **Step 5: Verify**

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A ancalagon tests pyproject.toml uv.lock README.md docs/architecture.md
git commit -m "Remove the JSON Schema route for answer files

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
