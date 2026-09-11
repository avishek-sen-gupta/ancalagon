# Embedding a Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Python program start an Ancalagon run by handing over a `Config` object, and stop every worker process from parsing TOML.

**Architecture:** One conversion layer at the top turns a representation — TOML, JSON, or Python — into a `Config`. Everything below it takes the `Config` and knows no format. A new `ancalagon/run.py` is that seam; `cli.py` becomes one of its callers. The `Config` reaches a worker process by being materialised into the run directory as JSON and parsed in one line.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-09-11-embedding-a-run-design.md`

## Global Constraints

- Pyright strict, ZERO errors. `Any` is banned outright — no `typing.Any`, no `dict[str, Any]`, no `object` annotations, no hand-rolled JSON aliases.
- Every generic parameterised: `dict[str, int]` not `dict`; `Sequence`, `Mapping`, `tuple` equally.
- NO COMMENTS except a single one-line header at the top of each module or class. No docstrings on functions, no inline explanations, no section dividers, no TODOs.
- All pydantic models `frozen=True`. Fully qualified imports, no relative imports. One class per file. No static methods.
- A class implementing a Protocol INHERITS it.
- No defensive programming: no `None` checks masking bugs, no bare `try/except`, no workaround guards. No `None` defaults, no `None` returns from non-`None` return types.
- python-fp-lint forbids `list.append(...)` and flags nested `for`/`if`. Rebuild lists (`xs = [*xs, x]`) or use comprehensions. It also caps cyclomatic complexity at 3 per function — split rather than nest.
- Text is a boundary, never a carrier. JSON exists only as text in files and becomes a model via `model_validate_json` the instant it enters Python.
- Tests: few tests, each covering a whole behaviour, with concrete value assertions — never `assert x is not None` where a concrete value is available.
- No mocking (`unittest.mock` banned). Use `FakeFileSystem`, `FakeClock` and the other injected fakes.
- Assertions are sacred: do not weaken or delete an existing assertion. If one now fails, that is a finding to report.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports`. Before the FINAL commit also run the whole `uv run python -m pytest tests/integration` — it takes about 65 seconds and two past plans let regressions through by narrowing it.
- Do NOT use `python -c` with multiline strings. Write a script into the scratchpad and run `uv run python <path>`.
- Talisman may flag markdown prose as a false-positive secret. Reword when the wording is incidental; otherwise APPEND a `.talismanrc` entry for a newly flagged file, or REPLACE THE CHECKSUM IN PLACE for one already listed. Never duplicate a filename. Use the checksum Talisman reports, never one from `shasum`.

---

### Task 1: The import anchor becomes data

**Files:**
- Modify: `ancalagon/config/config.py` — add one field
- Delete: `ancalagon/config/importable.py`
- Create: `ancalagon/config/on_path.py`
- Modify: `ancalagon/config/load.py:107-109` — stop mutating `sys.path`, set the field instead
- Modify: `ancalagon/cli.py` — call `on_path` before `check_contracts`
- Modify: `ancalagon/worker.py:179` — call `on_path` after loading the config
- Modify: `ancalagon/deterministic/run.py` — same
- Test: `tests/unit/test_config_load.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Config.import_paths: tuple[pathlib.PurePath, ...]`, defaulting to `()`
  - `on_path(paths: collections.abc.Sequence[pathlib.PurePath]) -> None` in `ancalagon/config/on_path.py`

**Why the rename.** The existing function is `importable(base)` in `ancalagon/config/importable.py`. `tests/unit/conftest.py:29` defines a **pytest fixture also named `importable`**, used by nine tests. Importing the production function into any of those files would shadow or be shadowed. The signature is changing anyway — from one path to a sequence — so the function is renamed to `on_path`, which also says what it does.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config_load.py`. Note this test does NOT take the `importable` fixture as a parameter — it manipulates `sys.path` itself and restores it.

```python
def test_a_config_carries_its_import_anchor_instead_of_load_mutating_the_path(
    tmp_path: pathlib.Path,
):
    before = list(sys.path)
    config = load_config(_written(tmp_path, ""), RealFileSystem())

    assert config.import_paths == (RealFileSystem().resolve(pathlib.PurePath(tmp_path)),)
    assert sys.path == before

    on_path(config.import_paths)

    assert str(tmp_path) in sys.path

    on_path(config.import_paths)

    assert sys.path.count(str(tmp_path)) == 1
    sys.path[:] = before
```

Add these imports at the top of the file, in their correct alphabetical positions:

```python
import sys

from ancalagon.config.on_path import on_path
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_config_load.py -k import_anchor -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.config.on_path'`

- [ ] **Step 3: Add the field**

In `ancalagon/config/config.py`, immediately after `web_domains: tuple[str, ...] = ()`:

```python
    import_paths: tuple[pathlib.PurePath, ...] = ()
```

- [ ] **Step 4: Replace the module**

Delete `ancalagon/config/importable.py`. Create `ancalagon/config/on_path.py`:

```python
# Puts a config's import anchors on sys.path, so its dotted contract classes resolve.
import collections.abc
import pathlib
import sys


def on_path(paths: collections.abc.Sequence[pathlib.PurePath]) -> None:
    fresh = [str(p) for p in paths if str(p) not in sys.path]
    sys.path = [*sys.path, *fresh]
```

- [ ] **Step 5: Stop the parser mutating global state**

In `ancalagon/config/load.py`, remove the `importable(base)` line from `load_config` and remove the `from ancalagon.config.importable import importable` import. Then add one field to the `Config(...)` construction, immediately after `sandbox=Strategy(raw["sandbox"]["strategy"]),`:

```python
        import_paths=(base,),
```

- [ ] **Step 6: Call it explicitly at all three entry points**

Three files each gain `from ancalagon.config.on_path import on_path` in the correct alphabetical position, plus one call.

`ancalagon/cli.py`, in `main`, immediately after `config = load_config(config_path, fs)` and BEFORE `check_contracts(config)`:

```python
    on_path(config.import_paths)
```

`ancalagon/worker.py`, in `main`, immediately after `config = load_config(config_path, fs)`:

```python
    on_path(config.import_paths)
```

`ancalagon/deterministic/run.py`, immediately after its own `load_config(...)` call — find it with `grep -n "load_config" ancalagon/deterministic/run.py`.

Ordering matters: `on_path` must run before any `resolve_class` call, because that is what imports the dotted module.

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_config_load.py -v`
Expected: PASS.

- [ ] **Step 8: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `on_path`, change the filter to `if True` so a path is added twice — the idempotence assertion must fail.
2. In `load_config`, change `import_paths=(base,)` to `import_paths=()` — the first assertion must fail.

Restore both.

- [ ] **Step 9: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

- [ ] **Step 10: Commit**

```bash
git add ancalagon/config ancalagon/cli.py ancalagon/worker.py ancalagon/deterministic/run.py tests/unit/test_config_load.py
git commit -m "$(cat <<'EOF'
Let a config carry the anchor its contract classes resolve against

Parsing a TOML file appended that file's directory to sys.path as a side
effect, which is the only reason a dotted contract class ever resolved. A
config built in Python has no directory, so the anchor becomes a field and
putting it on the path becomes a step an entry point takes.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The entry point

**Files:**
- Create: `ancalagon/run.py`
- Create: `ancalagon/check_contracts.py`
- Modify: `ancalagon/cli.py` — becomes a caller; loses what moved
- Modify: `pyproject.toml` — two new layers in the import contract
- Modify: `tests/unit/test_config_load.py`, `tests/unit/test_hooks.py` — `check_contracts` import moves
- Test: `tests/unit/test_run.py`

**Interfaces:**
- Consumes: `Config.import_paths` and `on_path` from Task 1.
- Produces:
  - `run(config: Config, run_dir: pathlib.PurePath, config_path: pathlib.PurePath, clock: Clock, fs: FileSystem) -> Outcome[pydantic.BaseModel]` in `ancalagon/run.py`
  - `check_contracts(config: Config, fs: FileSystem = RealFileSystem(), web: WebClient = RealWebClient()) -> None` in `ancalagon/check_contracts.py` — same signature it has today, new home
  - `root_spec`, `sandbox_of`, `goal_of` also live in `ancalagon/run.py`

**The `config_path` parameter is temporary.** Task 3 removes it, once the run materialises its own
config. It exists here so this task lands green on its own: workers still parse TOML until Task 3
changes them, so the spawner must still point at a TOML file.

**What moves, exactly.** Read `ancalagon/cli.py` in full first. Move to `ancalagon/check_contracts.py`: `check_contracts` and every private fault helper it calls (`_contract_fault`, `_run_fault`, `_submit_fault`, `_answer_file_fault`, `_hook_fault`, and anything those call). Move to `ancalagon/run.py`: `root_spec`, `sandbox_of`, `_spawner`, `goal_of`, `_text_of`, `_from_goal`. What stays in `cli.py`: `cli()`, argument parsing, `init_command`, and the thin `main` below.

- [ ] **Step 1: Write the failing test**

`run()` spawns real worker subprocesses, so this is an integration test, not a unit test. A role
whose `run` field names a deterministic function needs no model, which is what makes the test
possible offline. Read `tests/integration/test_deterministic_loop.py` first and copy its shape —
the generated package, the `importable` fixture, `prepared_run_dir`, and the TOML written into
`tmp_path`.

Create `tests/integration/test_embedded_run.py`:

```python
import collections.abc
import pathlib

from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.contracts.completed import Completed
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run import run
from tests.integration.prepared_run import prepared_run_dir

KIT = '''
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.deterministic.run_context import RunContext


class Said(pydantic.BaseModel, frozen=True):
    text: str


def speaks(given: FreeText, ctx: RunContext) -> Outcome[Said]:
    return Completed(value=Said(text=given.text), summary="spoke", spent=NOTHING)
'''

CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/no-model-is-called"
num_retries = 1
request_timeout_s = 60
max_tokens = 1000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[roles.root]
behaviour = "Say it."
run = { module = "speechkit.speech", name = "speaks" }
answer = { module = "speechkit.speech", name = "Said" }
tools = []
budget = { turns = 0, tool_calls = 0 }

[run]
goal_file = "./goal.md"
input_file = ""
role = "root"
"""


def test_a_run_hands_back_the_root_outcome_as_a_typed_value(
    tmp_path: pathlib.Path,
    importable: collections.abc.Callable[[pathlib.Path], None],
):
    fs = RealFileSystem()
    package = tmp_path / "speechkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "speech.py").write_text(KIT)
    importable(tmp_path)
    (tmp_path / "goal.md").write_text("Say hello.")
    config_path = tmp_path / "anc.toml"
    config_path.write_text(CONFIG)
    config = load_config(pathlib.PurePath(config_path), fs)
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "embedded")

    produced = run(config, run_dir, pathlib.PurePath(config_path), SystemClock(), fs)

    assert isinstance(produced, Completed)
    assert produced.value.text == "Say hello."
```

If `prepared_run_dir` has a different signature, or the deterministic role's input arrives in
another shape, read the real code and correct the test rather than loosening the assertion. The
`produced.value.text` assertion is the point of the test: `run` returns a parsed model, not text.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/integration/test_embedded_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.run'`

- [ ] **Step 3: Move the validation**

Create `ancalagon/check_contracts.py` with a one-line module header:

```python
# What a config must satisfy before a run starts: every contract it names must resolve.
```

Move `check_contracts` and its private fault helpers there verbatim, with their imports. Delete them from `cli.py`.

- [ ] **Step 4: Write the entry point**

Create `ancalagon/run.py`. It carries a one-line module header, the moved helpers, and:

```python
def run(
    config: Config,
    run_dir: pathlib.PurePath,
    config_path: pathlib.PurePath,
    clock: Clock,
    fs: FileSystem,
) -> Outcome[pydantic.BaseModel]:
    on_path(config.import_paths)
    check_contracts(config)
    task_dir = run_dir / "tasks" / "root"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    fs.write_text(task_dir / "spec.json", root_spec(config, fs).model_dump_json())
    db = run_dir / "bus.db"
    bus = LifecycleStore.open(db, clock, fs)
    bus.enqueue(task_dir, parent_agent=HUMAN)
    supervisor = Supervisor(
        bus=LifecycleStore.open(db, clock, fs),
        spawner=_spawner(config, run_dir, config_path, fs),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
        clock=clock,
        fs=fs,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()
    return _outcome_of(config, task_dir, bus, fs)
```

`_spawner` moves across from `cli.py` unchanged, still taking `config_path`. `SubprocessSpawner`
is not touched at all in this task.

`_outcome_of` reads the root's newest outcome file and parses it against the answer class its role declared:

```python
def _outcome_of(
    config: Config, task_dir: pathlib.PurePath, bus: LifecycleStore, fs: FileSystem
) -> Outcome[pydantic.BaseModel]:
    task = bus.task(task_dir)
    newest = newest_agent(bus.snapshot(), task.id)
    written = task_dir / f"outcome-{newest}.json"
    if not fs.exists(written):
        raise ValueError(f"root task produced no outcome; see {task_dir}")
    answer = resolve_class(config.roles[config.run.role].answer)
    adapter: pydantic.TypeAdapter[Outcome[pydantic.BaseModel]] = pydantic.TypeAdapter(
        Outcome[answer]
    )
    return adapter.validate_json(fs.read_text(written))
```

- [ ] **Step 5: Make the CLI a caller**

`cli.main` becomes:

```python
def main(config_path: pathlib.PurePath, run_dir: pathlib.PurePath) -> int:
    logging.basicConfig(level=logging.INFO)
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    try:
        produced = run(config, run_dir, config_path, SystemClock(), fs)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 1
    sys.stdout.write(produced.model_dump_json() + "\n")
    return 0
```

The `on_path` call Task 1 added to `cli.main` is removed, because `run()` now makes it.

- [ ] **Step 6: Update the import contract**

In `pyproject.toml`, in the `"Layers point downward"` contract, insert two entries immediately after `"ancalagon.cli",`:

```toml
    "ancalagon.run",
    "ancalagon.check_contracts",
```

- [ ] **Step 7: Move the test imports**

Find every importer and change it:

```bash
grep -rn "from ancalagon.cli import" tests/
```

`check_contracts` now comes from `ancalagon.check_contracts`. Anything importing `goal_of`, `root_spec` or `sandbox_of` from `ancalagon.cli` now imports from `ancalagon.run`. Do not trust a count — grep and fix what you find.

- [ ] **Step 8: Run the tests**

```bash
uv run python -m pytest tests/unit -v
uv run python -m pytest tests/integration/test_embedded_run.py -v
```
Expected: both PASS.

- [ ] **Step 9: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `_outcome_of`, return `Completed(value=Said(text="wrong"), ...)` built from scratch instead of parsing the file — `test_a_run_hands_back_the_root_outcome_as_a_typed_value` must fail on `produced.value.text`.
2. In `run()`, delete the `check_contracts(config)` call — a test in `tests/unit/test_hooks.py` that expects a refusal must fail.

Restore both.

- [ ] **Step 10: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

- [ ] **Step 11: Commit**

```bash
git add ancalagon tests pyproject.toml
git commit -m "$(cat <<'EOF'
Give a run an entry point that takes a config and returns an outcome

cli.main configured logging, wrote JSON to stdout and returned an exit
code, so a program that wanted the answer got a side effect and an
integer. The run itself now takes a Config and hands back the typed
outcome its root role declared.

Validating a config was never CLI work, so it moves down with the two
other things a run needs before it starts.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The config crosses the process boundary once

**Files:**
- Modify: `ancalagon/run.py` — materialise the config
- Modify: `ancalagon/supervisor/subprocess_spawner.py` — `config_path` becomes derived, not given
- Modify: `ancalagon/worker.py` — parse JSON, not TOML
- Modify: `ancalagon/deterministic/run.py` — same
- Test: `tests/unit/test_run.py`, `tests/integration/test_embedded_run.py`

**Interfaces:**
- Consumes: `run()` and `_spawner` from Task 2; `Config.import_paths` and `on_path` from Task 1.
- Produces:
  - `run(config, run_dir, clock, fs) -> Outcome[pydantic.BaseModel]` — `config_path` is gone
  - `CONFIG = "config.json"` in `ancalagon/run.py`
  - `run_dir/config.json`, holding `config.model_dump_json()`

- [ ] **Step 1: Rewrite the integration test to use no TOML**

`tests/integration/test_embedded_run.py` exists from Task 2 and currently writes a TOML file. Its
whole point now changes: the config is built in Python and no TOML exists anywhere. This is the
case that fails today and the reason for the design.

Delete the `CONFIG` TOML constant and the `load_config` import. Replace the body of
`test_a_run_hands_back_the_root_outcome_as_a_typed_value` so it builds the `Config` directly. Keep
`KIT` and the package setup exactly as they are.

```python
def test_a_run_hands_back_the_root_outcome_as_a_typed_value(
    tmp_path: pathlib.Path,
    importable: collections.abc.Callable[[pathlib.Path], None],
):
    fs = RealFileSystem()
    package = tmp_path / "speechkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "speech.py").write_text(KIT)
    importable(tmp_path)
    (tmp_path / "goal.md").write_text("Say hello.")

    config = Config(
        write_root=pathlib.PurePath(tmp_path / "ws"),
        read_roots=(pathlib.PurePath(tmp_path / "ws"),),
        model="some-provider/no-model-is-called",
        roles={
            "root": Role(
                behaviour="Say it.",
                run=FunctionRef(module="speechkit.speech", name="speaks"),
                answer=ClassRef(module="speechkit.speech", name="Said"),
                tools=(),
                budget=Budget(turns=Finite(value=0), tool_calls=Finite(value=0)),
            )
        },
        run=RunSettings(goal_file=str(tmp_path / "goal.md"), role="root"),
        sandbox=Strategy.NONE,
        import_paths=(pathlib.PurePath(tmp_path),),
    )
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "embedded")

    produced = run(config, run_dir, SystemClock(), fs)

    assert isinstance(produced, Completed)
    assert produced.value.text == "Say hello."
    assert list(pathlib.Path(run_dir).glob("*.toml")) == []
```

The import block changes: drop `load_config`, add `Config`, `Budget`, `ClassRef`, `Finite`,
`FunctionRef`, `Role`, `RunSettings` and `Strategy`. Sort them with
`uv run ruff check --select I --fix tests/`.

Add one unit test to a new `tests/unit/test_run.py` for the materialised file itself:

```python
import pathlib

from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run import CONFIG


def test_a_materialised_config_round_trips(tmp_path: pathlib.Path):
    source = tmp_path / "anc.toml"
    source.write_text(TEMPLATE)
    given = load_config(pathlib.PurePath(source), RealFileSystem())
    written = tmp_path / CONFIG
    written.write_text(given.model_dump_json())

    assert Config.model_validate_json(written.read_text()) == given
```

`TEMPLATE` is the minimal valid config. Copy it from `tests/unit/test_config_load.py:19` rather
than writing a new one, and use that file's `_written` helper if it is simpler.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/unit/test_run.py tests/integration/test_embedded_run.py -v`
Expected: FAIL — `run()` still requires a `config_path` argument, and `CONFIG` is not defined.

- [ ] **Step 3: Materialise the config**

In `ancalagon/run.py`, add the constant at module level:

```python
CONFIG = "config.json"
```

Drop the `config_path` parameter from `run()`. Immediately after `check_contracts(config)`:

```python
    fs.mkdir(run_dir, parents=True, exist_ok=True)
    fs.write_text(run_dir / CONFIG, config.model_dump_json())
```

This runs on every invocation, so a resumed run overwrites it and an existing run directory needs
no migration.

- [ ] **Step 4: Point the spawner at it**

`_spawner` loses its `config_path` parameter too, and passes `run_dir / CONFIG` to both
`SubprocessSpawner` constructions instead.

`ancalagon/supervisor/subprocess_spawner.py` is NOT touched. It sits below `ancalagon.run` in the
layer contract, so it cannot import `CONFIG`; it keeps taking the path it is given. One definition
of the filename, no layer violation.

Then update `cli.main` to drop the argument it passes.

- [ ] **Step 5: Stop the workers parsing TOML**

In `ancalagon/worker.py`, replace:

```python
    config = load_config(config_path, fs)
```

with:

```python
    config = Config.model_validate_json(fs.read_text(config_path))
```

Remove the now-unused `from ancalagon.config.load import load_config` import and add `from ancalagon.config.config import Config` if it is not already there.

Do exactly the same in `ancalagon/deterministic/run.py`.

The `on_path(config.import_paths)` call Task 1 added stays in both, immediately after this line.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run python -m pytest tests/unit/test_run.py -v
uv run python -m pytest tests/integration/test_embedded_run.py -v
```
Expected: PASS.

If the integration test fails because a worker cannot import `speechkit`, the `import_paths` are not reaching the child. That is the real defect this task exists to fix — debug it rather than making the test tolerate it.

- [ ] **Step 7: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `run()`, delete the `fs.write_text(run_dir / CONFIG, ...)` line — the integration test must fail, because the worker it spawns has no config to read.
2. In `worker.py` and `deterministic/run.py`, pass `()` to `on_path` instead of `config.import_paths` — the integration test must fail with an import error naming `speechkit`.

Restore both.

- [ ] **Step 8: Verify**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run lint-imports
```

- [ ] **Step 9: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Hand a worker a config instead of a file to parse

A worker runs one agent, so a config format has no business in it. The
run materialises its config into the run directory and the worker parses
one line of JSON. TOML parsing, the Raw models and relative path
resolution stop existing below the supervisor.

A run directory now also records what the run was allowed to reach, which
nothing did before.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md` — the partial-freeze paragraph, and a note on the embedding surface
- Modify: `docs/architecture.md` — the trace through `cli.py`, and what a run leaves behind
- Modify: `.talismanrc` — only if Talisman flags a changed file

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Correct the partial-freeze claim**

`README.md` states that a `spec.json` freezes the role at enqueue and that the freeze is not total. Find it:

```bash
grep -n "freeze is not total\|resolved fresh" README.md
```

That paragraph is now wrong in one respect and right in another. Rewrite it to say: the config is fixed for the duration of one `run()` invocation, because the run materialises it into the run directory and every worker reads that copy; editing `[roles.*]`, the model or the limits affects the next invocation, not the next worker spawned. Keep the part that is still true — a contract *source* is a dotted module resolved fresh each time a worker starts, so editing the Python changes the shape a resumed run works to.

Match the README's existing register: plain declarative sentences, lowercase identifiers in backticks, no marketing language.

- [ ] **Step 2: Document the embedding surface**

Add a short section to `README.md` after the `## Running` section. It must show the real signature and say the one thing a host has to know:

```markdown
## Starting a run from Python

`ancalagon run` is one caller of a seam any program can use:

```python
from ancalagon.run import run

produced = run(config, run_dir, SystemClock(), RealFileSystem())
```

`run` takes a `Config` and returns the root's `Outcome`, parsed against the answer class its role
declared. A `Config` comes from `load_config` for a TOML file, from `Config.model_validate_json`
for a JSON one, or from Python directly — the conversion layer sits above the run, and nothing
below it knows a format exists.

A `Config` built in Python must set `import_paths` to the directories its contract classes and
hook functions live under. `load_config` sets it to the config file's own directory.
```

- [ ] **Step 3: Correct the architecture trace**

`docs/architecture.md` walks through `cli.py` under `### 1. Starting a run`. Read enough of that section to match its register, then correct it: the CLI loads a config and calls `run`, and `run` is where validation, materialisation, enqueue and supervision happen. Add `config.json` to the section describing what a run leaves behind.

Find both places first:

```bash
grep -n "cli.py\|What a run leaves behind" docs/architecture.md
```

- [ ] **Step 4: Full verification**

This is the last commit of the plan, so run everything including the whole integration suite:

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

Expected: Black clean, Pyright zero errors, both suites green, all import contracts kept. `tests/integration` takes about 65 seconds. Do not narrow it to the file you expect to break.

- [ ] **Step 5: Grep for anything left behind**

```bash
grep -rn "importable\|load_config\|config_path" ancalagon --include="*.py" | grep -v pycache
```

Every remaining hit must be intentional. `load_config` should now appear only in `ancalagon/config/load.py` and `ancalagon/cli.py`. The name `importable` should appear nowhere under `ancalagon/` — it survives only as a pytest fixture under `tests/`.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/architecture.md .talismanrc
git commit -m "$(cat <<'EOF'
Document the run seam and correct what a config freeze means

A config is now fixed for one run invocation rather than for one worker
spawn, so the README paragraph describing the partial freeze was wrong in
one respect. The architecture trace gains the same correction, and a run
directory's contents gain the config it ran under.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- The spec is `docs/superpowers/specs/2026-09-11-embedding-a-run-design.md`. Read it before Task 1. It records why several obvious alternatives were rejected — passing the config on stdin, making the config format JSON — so you do not re-propose them.
- The config format does not change. TOML stays the authoring language. JSON is the resolved machine form. Do not convert any `.toml` in the repo.
- `Task 2, Step 1` ships a deliberately weak assertion with instructions to replace it. Do not commit it as written, and say in your report which way you resolved it.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
