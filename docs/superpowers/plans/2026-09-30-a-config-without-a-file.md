# A config without a file — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a caller that does not import ancalagon start a run by piping its whole configuration to the CLI as JSON, while TOML files keep loading exactly as they do now.

**Architecture:** State the TOML document as a Pydantic model (`RawConfig`), then split `load.py` into a TOML reader and the shared step that turns a `RawConfig` into a `Config`. A second reader validates the same model from JSON on stdin. The document declares its own `base` — the anchor a file supplies by its location — so both readers resolve relative paths and import anchors identically.

**Tech Stack:** Python 3.13, Pydantic v2, `tomllib` (stdlib), `argparse`, pytest, Black, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-09-30-a-config-without-a-file-design.md`

## Global Constraints

- Pyright runs in **strict** mode and must pass with **zero** errors. `uv run pyright`.
- **`Any` and `object` are banned outright.** No `from typing import Any`, no `: Any`, no `dict[str, Any]`, no `: object`. The only exemption in the codebase is `Citation.other_data` / `CiteArgs.other_data`; this plan adds no others.
- **No comments** except a one-line header on a class or module stating its purpose. No docstrings on functions.
- **No bare collection types.** Every generic is parameterised.
- Dataclasses are `frozen=True`; Pydantic models are declared `pydantic.BaseModel, frozen=True`.
- **Fully qualified imports.** `from ancalagon.config.raw_config import RawConfig`, never relative.
- **One class per file** for domain types. `raw_config.py` is the one exception already established by `raw_role.py`, which holds four related raw models; follow that precedent.
- Functional style: comprehensions over `for` loops with mutation. Early return.
- **No mocking.** No `unittest.mock.patch`. Use `RealFileSystem()` with `tmp_path`.
- **Few tests, each covering a whole behaviour.** Extend an existing behaviour test rather than adding a file, wherever one exists.
- Black line length **100**, target `py313`. `uv run python -m black .`
- Verify with: `uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports`
- `tests/integration` runs **whole**, never narrowed to the one file the change is about. It takes about forty seconds.
- Never reference an external codebase under analysis in any tracked artifact. Test fixtures use invented package names (`shapekit`, `runkit`, `speechkit` are the established ones).

## Review Focus

Five conditions the spec implies that a naive implementation gets wrong, most likely to bite first. Each has a test assigned to the task that owns the code.

1. **`base` naming a directory that does not exist.** `fs.resolve` succeeds on a non-existent path, so a typo in the anchor would surface much later as an unresolvable `read_root` or an `ImportError` on a role. Expected: refused at load, naming the directory. → **Task 2, Step 1.**
2. **`--config-json` with stdin attached to a terminal.** `sys.stdin.read()` on a TTY blocks forever. For a caller in CI that is the worst failure mode there is — a hang, not an error. Expected: refused immediately when stdin is a TTY. → **Task 2, Step 1.**
3. **A relative `base`.** It would resolve against the process's working directory, silently restoring the cwd dependence that declaring `base` exists to remove. Expected: refused, naming the value. → **Task 2, Step 1.**
4. **Neither `--config` nor `--config-json` given.** An `add_mutually_exclusive_group()` without `required=True` accepts both being absent, leaving `args.config` as `None` and failing obscurely inside `load_config`. Expected: argparse refuses with a usage message. → **Task 2, Step 9.**
5. **A document that differs between the `init` spawn and the `run` spawn.** `init` allocates the run directory under `config.home`; `run` reads `config.home` again. If they disagree, the run directory is outside the home and the first tool that writes raises `ScopeError` — which `README.md` already lists as failing "later than you would like". Expected: documented as a caller obligation in the README section this plan adds. → **Task 2, Step 11.**

---

### Task 1: `RawConfig`, and the reader split from the resolution

No new capability. `load_config` keeps its signature, so nothing outside `ancalagon/config` changes. The diff answers one question: is this the same document, stated as a model?

**Files:**
- Create: `ancalagon/config/raw_config.py`
- Create: `ancalagon/config/from_raw.py`
- Modify: `ancalagon/config/load.py` (reduced to the TOML reader)
- Test: `tests/unit/test_config_load.py` (extend existing behaviours)

**Interfaces:**
- Consumes: `RawRole`, `RawClassRef` from `ancalagon/config/raw_role.py`; `Strategy`; `Config`; `FileSystem`.
- Produces:
  - `RawConfig` and its nested models `RawWorkspace`, `RawModel`, `RawLimits`, `RawRun`, `RawSandbox`, `RawLog`, `RawWeb` in `ancalagon.config.raw_config`.
  - `config_from(raw: RawConfig, base: pathlib.PurePath, fs: FileSystem) -> Config` in `ancalagon.config.from_raw`.
  - `TOML_STATES_NO_BASE: str` in `ancalagon.config.load`.
  - `load_config(path: pathlib.PurePath, fs: FileSystem) -> Config` — unchanged signature.

- [ ] **Step 1: Change the two assertions that must change, and watch them fail**

`test_the_run_section_is_required_and_names_its_fields` asserts `pytest.raises(KeyError)` twice. Those `KeyError`s come from bracket-indexing the parsed dict, which this task removes — Pydantic raises `ValidationError` instead. This is the one assertion change in the plan and it is justified by the mechanism changing, not by a test being inconvenient. **Do not weaken it to a bare `Exception`.** Assert the stronger thing the new mechanism gives you: every missing key reported at once.

In `tests/unit/test_config_load.py`, replace lines 106-115 (both `with pytest.raises(KeyError):` blocks) with:

```python
    with pytest.raises(pydantic.ValidationError) as absent:
        load_config(_config_file(tmp_path, "absent.toml", ""), RealFileSystem())
    assert "run" in str(absent.value)

    with pytest.raises(pydantic.ValidationError) as partial:
        load_config(
            _config_file(
                tmp_path,
                "partial.toml",
                '[run]\ngoal_file = ""\ninput_file = ""\n',
            ),
            fs=RealFileSystem(),
        )
    assert "role" in str(partial.value)
```

Then add a new behaviour to the same file, which is the improvement worth pinning:

```python
def test_every_missing_key_is_reported_at_once(tmp_path: pathlib.Path):
    path = tmp_path / "sparse.toml"
    path.write_text('[workspace]\nhome = "./ws"\n')

    with pytest.raises(pydantic.ValidationError) as raised:
        load_config(pathlib.PurePath(path), RealFileSystem())

    reported = str(raised.value)
    assert "write_roots" in reported
    assert "read_roots" in reported
    assert "model" in reported
    assert "limits" in reported
    assert "run" in reported
    assert "sandbox" in reported
```

- [ ] **Step 2: Run the tests to confirm the shape of the failure**

Run: `uv run pytest tests/unit/test_config_load.py -v`

Expected: `test_the_run_section_is_required_and_names_its_fields` FAILS (`DID NOT RAISE ValidationError` — it raises `KeyError`), and `test_every_missing_key_is_reported_at_once` FAILS with `KeyError: 'write_roots'`, because today's loader stops at the first missing key.

- [ ] **Step 3: Write `raw_config.py`**

Create `ancalagon/config/raw_config.py`:

```python
# One config document exactly as TOML or JSON presents it, before paths are resolved.
import pydantic

from ancalagon.config.raw_role import RawRole
from ancalagon.sandbox.strategy import Strategy


class RawWorkspace(pydantic.BaseModel, frozen=True):
    home: str
    write_roots: list[str]
    read_roots: list[str]


class RawModel(pydantic.BaseModel, frozen=True):
    name: str
    custom_llm_provider: str = ""
    num_retries: int
    request_timeout_s: int
    max_tokens: int
    allowed_domains: list[str]


class RawLimits(pydantic.BaseModel, frozen=True):
    max_concurrent_agents: int
    agent_timeout_s: int
    max_depth: int
    compact_above_tokens: int
    keep_recent_messages: int
    summary_chars: int


class RawRun(pydantic.BaseModel, frozen=True):
    goal_file: str
    input_file: str
    role: str


class RawSandbox(pydantic.BaseModel, frozen=True):
    strategy: Strategy


class RawLog(pydantic.BaseModel, frozen=True):
    socket: str = ""


class RawWeb(pydantic.BaseModel, frozen=True):
    allowed_domains: list[str] = []


class RawConfig(pydantic.BaseModel, frozen=True):
    workspace: RawWorkspace
    model: RawModel
    limits: RawLimits
    run: RawRun
    sandbox: RawSandbox
    base: str = pydantic.Field(
        default="",
        description="Absolute directory relative paths resolve against, and the import anchor "
        "for dotted module refs. Required for a document on stdin; refused in a TOML file, "
        "whose own directory is used.",
    )
    log: RawLog = RawLog()
    web: RawWeb = RawWeb()
    roles: dict[str, RawRole] = {}
```

Every field with no default is one `load.py` reads by bracket today; every field with a default is one it reads with `.get()`. Do not add defaults to the others — a document must still be complete.

- [ ] **Step 4: Write `from_raw.py` by moving, not rewriting**

Create `ancalagon/config/from_raw.py`. Move `_root`, `_optional_root`, `_run_settings`, `_class_ref`, `_hooks`, `_contracts`, `_allowance` and `_role` out of `load.py` **unchanged**, along with `ROLE_NAME` and the `on_path` call. Change only the three signatures that took a raw mapping so they take the raw model:

```python
# Turns a validated config document into the Config a run is given.
import collections.abc
import pathlib
import re
import typing

from ancalagon.config.config import Config
from ancalagon.config.on_path import on_path
from ancalagon.config.raw_config import RawConfig, RawRun
from ancalagon.config.raw_role import RawClassRef, RawRole
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.infinite import Infinite
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT, Role
from ancalagon.contracts.run_contracts import run_contracts
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.fs.file_system import FileSystem


def _run_settings(base: pathlib.PurePath, run: RawRun, fs: FileSystem) -> RunSettings:
    return RunSettings(
        goal_file=_optional_root(base, run.goal_file, fs),
        input_file=_optional_root(base, run.input_file, fs),
        role=run.role,
    )


def config_from(raw: RawConfig, base: pathlib.PurePath, fs: FileSystem) -> Config:
    on_path((base,))
    return Config(
        home=_root(base, raw.workspace.home, fs),
        write_roots=tuple(_root(base, p, fs) for p in raw.workspace.write_roots),
        read_roots=tuple(_root(base, p, fs) for p in raw.workspace.read_roots),
        roles={name: _role(name, table) for name, table in raw.roles.items()},
        model=raw.model.name,
        custom_llm_provider=raw.model.custom_llm_provider,
        max_tokens=raw.model.max_tokens,
        num_retries=raw.model.num_retries,
        request_timeout_s=raw.model.request_timeout_s,
        max_concurrent_agents=raw.limits.max_concurrent_agents,
        agent_timeout_s=raw.limits.agent_timeout_s,
        max_depth=raw.limits.max_depth,
        summary_chars=raw.limits.summary_chars,
        compact_above_tokens=raw.limits.compact_above_tokens,
        keep_recent_messages=raw.limits.keep_recent_messages,
        run=_run_settings(base, raw.run, fs),
        allowed_domains=tuple(raw.model.allowed_domains),
        web_domains=tuple(raw.web.allowed_domains),
        sandbox=raw.sandbox.strategy,
        log_socket=raw.log.socket,
        import_paths=(base,),
    )
```

Two things that are easy to get wrong here:

- `_role` previously took `RawRole.model_validate(table)`; it now receives an already-validated `RawRole` straight from `raw.roles`. Delete the `model_validate` call inside the comprehension — validating twice is the defect the boundary rules name.
- `sandbox=raw.sandbox.strategy` is already a `Strategy`. Do **not** wrap it in `Strategy(...)`.

`on_path` must stay before the `roles` comprehension is evaluated. Calling it on the first line of `config_from` satisfies that, because Python evaluates the `Config(...)` arguments after the function body's first statement.

- [ ] **Step 5: Reduce `load.py` to the TOML reader**

Replace the whole of `ancalagon/config/load.py` with:

```python
# Loads a Config from a TOML file on disk.
import pathlib
import tomllib

from ancalagon.config.config import Config
from ancalagon.config.from_raw import config_from
from ancalagon.config.raw_config import RawConfig
from ancalagon.fs.file_system import FileSystem

SPLIT_WRITE_ROOT = (
    "[workspace] write_root was split into home (where runs live) and "
    "write_roots (where agents may write)"
)

TOML_STATES_NO_BASE = (
    "[base] is for a document with no file. A TOML file's own directory is its base, "
    "so remove it"
)


def load_config(path: pathlib.PurePath, fs: FileSystem) -> Config:
    document = tomllib.loads(fs.read_text(path))
    if "write_root" in document.get("workspace", {}):
        raise ValueError(SPLIT_WRITE_ROOT)
    raw = RawConfig.model_validate(document)
    if raw.base:
        raise ValueError(TOML_STATES_NO_BASE)
    return config_from(raw, fs.resolve(path).parent, fs)
```

`.get("workspace", {})` and not `["workspace"]`: a document with no `[workspace]` table must be reported by Pydantic along with every other missing key, not by a `KeyError` from this check.

- [ ] **Step 6: Add the `base`-in-TOML refusal test**

Append to `tests/unit/test_config_load.py`:

```python
def test_a_toml_file_may_not_state_a_base(tmp_path: pathlib.Path):
    path = tmp_path / "based.toml"
    path.write_text('base = "/somewhere"\n' + TEMPLATE.format(run=REQUIRED_RUN, block=""))

    with pytest.raises(ValueError, match="own directory is its base"):
        load_config(pathlib.PurePath(path), RealFileSystem())
```

The `base = ...` line goes **before** `TEMPLATE`, not into its `{block}` slot. `{block}` sits at the
end of the file after `[sandbox]`, so a bare key there would belong to the `[sandbox]` table and
the test would fail for the wrong reason. In TOML a top-level key must precede the first table
header.

- [ ] **Step 7: Run the whole unit suite**

Run: `uv run pytest tests/unit -v`

Expected: PASS, including `test_the_example_config_this_repo_ships_satisfies_its_own_contracts` and `test_the_research_config_this_repo_ships_types_every_answer_file` — those two load `ancalagon.example.toml` and `research.toml` whole, and they are the net that catches a field or default `RawConfig` got wrong. If either fails, a field is missing or a default drifted; do not adjust the test.

- [ ] **Step 8: Check the sandbox strategy message**

`config.sandbox` is now validated by Pydantic rather than by `Strategy(...)`, so a bad value produces a different message.

Run: `uv run pytest tests/unit/test_config_load.py -k sandbox -v`

Expected: PASS. `test_the_sandbox_strategy_and_its_domains_come_from_the_config` asserts `config.sandbox is Strategy.FENCE`, which is unaffected. If any test asserts on the *text* of a bad-strategy error, update it to Pydantic's wording and say so in the commit message.

- [ ] **Step 9: Mutation-check the new test**

Break `RawConfig` in the two most obvious ways and confirm the failure lands where this plan says:

1. Give `RawLimits.summary_chars` a default of `1000`. Expected: `test_every_missing_key_is_reported_at_once` still passes (it does not name that key) but the document is no longer required to be complete — so also confirm `test_the_example_config_this_repo_ships_satisfies_its_own_contracts` still passes and that you have genuinely weakened the contract. Revert.
2. Remove the `on_path((base,))` line from `config_from`. Expected: `test_load_config_puts_the_file_s_own_directory_on_the_path_before_parsing_roles` FAILS. Revert.

A test written after the code is a hypothesis until it has failed once.

- [ ] **Step 10: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

Expected: Black reformats nothing unexpected, Pyright reports zero errors, both suites pass, all seven import contracts kept. `ancalagon.config.from_raw` imports only from packages at or below `ancalagon.config` in the layers list in `pyproject.toml`, so no contract changes.

```bash
git add ancalagon/config/raw_config.py ancalagon/config/from_raw.py ancalagon/config/load.py tests/unit/test_config_load.py
git commit -m "State the config document as a model

load.py read five of the six tables by bracket-indexing the dict tomllib
returns, which is the one place the codebase indexed a parsed dict.
RawConfig states the document; from_raw.py holds the step that turns one
into a Config, so load.py is the TOML reader and nothing else.

Missing keys are now reported together rather than one KeyError at a time.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The JSON reader and `--config-json`

**Files:**
- Create: `ancalagon/config/from_json.py`
- Create: `tests/unit/test_config_from_json.py`
- Modify: `ancalagon/cli.py`
- Modify: `README.md`, `docs/architecture.md`
- Test: `tests/integration/test_config_on_stdin.py` (create)

**Interfaces:**
- Consumes: `config_from`, `RawConfig`, `load_config` from Task 1.
- Produces:
  - `config_from_json(document: str, fs: FileSystem) -> Config` in `ancalagon.config.from_json`.
  - `JSON_STATES_ITS_BASE: str`, `BASE_IS_ABSOLUTE: str`, `BASE_IS_A_DIRECTORY: str`, `STDIN_IS_A_TERMINAL: str` in `ancalagon.config.from_json`.
  - `--config-json` on the `run` and `init` subcommands, mutually exclusive with `--config`.

- [ ] **Step 1: Write the failing test for the reader**

Create `tests/unit/test_config_from_json.py`. One behaviour — the two readers agree — plus the four refusals from the Review Focus:

```python
import collections.abc
import json
import pathlib
import tomllib

import pytest

from ancalagon.config.from_json import (
    BASE_IS_ABSOLUTE,
    BASE_IS_A_DIRECTORY,
    JSON_STATES_ITS_BASE,
    config_from_json,
)
from ancalagon.config.load import load_config
from ancalagon.fs.real_file_system import RealFileSystem

TOML = """
[workspace]
home = "./ws"
write_roots = ["./notes"]
read_roots = ["./artifacts"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = ["bedrock-runtime.us-east-1.amazonaws.com"]

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "fence"

[log]
socket = "/tmp/anc.sock"

[web]
allowed_domains = ["*.example.com"]

[roles.analyst]
behaviour = "Analyse."
answer = { module = "shapekit.shapes", name = "Component" }
tools = ["read_file", "delegate_scout", "submit_answer"]
budget = { turns = 12, tool_calls = 30 }

[roles.analyst.before]
submit_answer = [{ module = "shapekit.shapes", name = "always_fine" }]

[roles.scout]
behaviour = "Investigate."
tools = ["read_file", "submit_answer"]
budget = { turns = "infinite", tool_calls = 8 }

[run]
goal_file = "./goal.md"
input_file = ""
role = "analyst"
"""

KIT = """
import pydantic

from ancalagon.contracts.free_text import FreeText


class Component(pydantic.BaseModel, frozen=True):
    name: str


def always_fine(answer: FreeText) -> str:
    return ""
"""


def _document(extra: dict[str, str]) -> str:
    return json.dumps({**tomllib.loads(TOML), **extra})


def test_the_json_reader_and_the_toml_reader_agree_on_one_document(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(KIT)
    importable(tmp_path)
    (tmp_path / "config.toml").write_text(TOML)
    fs = RealFileSystem()

    from_toml = load_config(pathlib.PurePath(tmp_path / "config.toml"), fs)
    from_json = config_from_json(_document({"base": str(tmp_path)}), fs)

    assert from_json == from_toml


def test_a_document_states_an_absolute_base_that_is_a_directory(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    package = tmp_path / "shapekit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "shapes.py").write_text(KIT)
    importable(tmp_path)
    fs = RealFileSystem()

    with pytest.raises(ValueError, match="states its base"):
        config_from_json(_document({}), fs)

    with pytest.raises(ValueError, match="must be absolute"):
        config_from_json(_document({"base": "./ws"}), fs)

    absent = tmp_path / "nowhere"
    with pytest.raises(ValueError, match="not a directory"):
        config_from_json(_document({"base": str(absent)}), fs)
```

Two things about the shape of this test.

`_document` is built from `tomllib.loads(TOML)` rather than as a dict literal written out by hand.
That is deliberate: the test's whole claim is that the two readers agree on **one** document, and a
hand-written dict beside the TOML would be two documents that drift. Building one from the other
means a field added to `RawConfig` but forgotten in either reader shows up here.

`assert from_json == from_toml` is the assertion that carries this task. Both are frozen Pydantic
models, so equality compares every field — every root, every role, every contract ref, every
budget, `import_paths` included. It fails if either reader drifts, which is the only thing worth
asserting here. Do not weaken it to comparing selected fields.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_from_json.py -v`

Expected: FAIL at import — `ModuleNotFoundError: No module named 'ancalagon.config.from_json'`.

- [ ] **Step 3: Write `from_json.py`**

Create `ancalagon/config/from_json.py`:

```python
# Loads a Config from a JSON document with no file behind it.
import pathlib
import typing

from ancalagon.config.config import Config
from ancalagon.config.from_raw import config_from
from ancalagon.config.raw_config import RawConfig
from ancalagon.fs.file_system import FileSystem

JSON_STATES_ITS_BASE = (
    "a document with no file states its base: the absolute directory its relative paths "
    "resolve against, and the import anchor for its dotted module refs"
)

BASE_IS_ABSOLUTE = (
    "base is {base}, which is relative. A document read from stdin has no location to "
    "resolve it against, so it must be absolute"
)

BASE_IS_A_DIRECTORY = "base names {base}, which is not a directory"


def config_from_json(document: str, fs: FileSystem) -> Config:
    raw = RawConfig.model_validate_json(document)
    if not raw.base:
        raise ValueError(JSON_STATES_ITS_BASE)
    base = fs.expanduser(pathlib.PurePath(raw.base))
    if not base.is_absolute():
        raise ValueError(BASE_IS_ABSOLUTE.format(base=base))
    if not fs.is_dir(base):
        raise ValueError(BASE_IS_A_DIRECTORY.format(base=base))
    return config_from(raw, fs.resolve(base), fs)
```

`model_validate_json` on the text, not `json.loads` then `model_validate`. Text in, instance out,
one hop.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config_from_json.py -v`

Expected: PASS, both tests.

- [ ] **Step 5: Mutation-check both new tests**

1. In `config_from_json`, replace `config_from(raw, fs.resolve(base), fs)` with `config_from(raw, fs.resolve(pathlib.PurePath.cwd()), fs)` — i.e. ignore `base`. Expected: `test_the_json_reader_and_the_toml_reader_agree_on_one_document` FAILS on the `read_roots` comparison. Revert.
2. Delete the `if not base.is_absolute():` block. Expected: `test_a_document_states_an_absolute_base_that_is_a_directory` FAILS with `DID NOT RAISE` on the relative case — or passes for the wrong reason via the directory check, in which case make the relative value one that *does* exist relative to cwd and confirm it fails. Revert.

- [ ] **Step 6: Write the failing CLI test**

The stdin-is-a-TTY guard belongs with the CLI, since it is about how the document arrives. Append
to `tests/unit/test_config_from_json.py`:

```python
def test_reading_a_document_from_a_terminal_is_refused_rather_than_blocking():
    with pytest.raises(ValueError, match="pipe the document"):
        document_on_stdin(_Terminal())
```

with a fake at the top of the file, because there is no mocking in this codebase:

```python
class _Terminal:
    def isatty(self) -> bool:
        return True

    def read(self) -> str:
        raise AssertionError("a terminal must be refused before it is read")


class _Pipe:
    def __init__(self, text: str) -> None:
        self._text = text

    def isatty(self) -> bool:
        return False

    def read(self) -> str:
        return self._text
```

and the companion behaviour:

```python
def test_a_piped_document_is_read_whole():
    assert document_on_stdin(_Pipe('{"base": "/x"}')) == '{"base": "/x"}'
```

`_Terminal.read` raising is the point: it proves the guard fires *before* the blocking read, which
is the failure mode being prevented. A test that only checked the message would pass even if the
implementation read first and checked afterwards.

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_config_from_json.py -k terminal -v`

Expected: FAIL — `ImportError: cannot import name 'document_on_stdin'`.

- [ ] **Step 8: Write `document_on_stdin`**

Add to `ancalagon/config/from_json.py`:

```python
STDIN_IS_A_TERMINAL = (
    "--config-json reads the document from stdin, and stdin is a terminal: "
    "pipe the document in, or use --config with a TOML file"
)


class Stdin(typing.Protocol):
    def isatty(self) -> bool: ...

    def read(self) -> str: ...


def document_on_stdin(stdin: Stdin) -> str:
    if stdin.isatty():
        raise ValueError(STDIN_IS_A_TERMINAL)
    return stdin.read()
```

`Stdin` is structural rather than inherited, for the reason `CLAUDE.md` gives for `Process`: it is
the shape of `sys.stdin`, which cannot inherit anything of ours.

- [ ] **Step 9: Wire the CLI**

In `ancalagon/cli.py`, add the import and change the two parsers and the two commands.

```python
from ancalagon.config.config import Config
from ancalagon.config.from_json import config_from_json, document_on_stdin
from ancalagon.fs.file_system import FileSystem
```

`cli.py` imports `load_config` today but neither `Config` nor `FileSystem`; `_chosen_config` needs
both for its signature. Check before adding — Pyright will flag an unused import if one is already
there.

Replace the `run_parser` and `init` blocks:

```python
    run_parser = commands.add_parser("run")
    run_where = run_parser.add_mutually_exclusive_group(required=True)
    run_where.add_argument("--config", type=pathlib.PurePath)
    run_where.add_argument("--config-json", action="store_true", dest="config_json")
    run_parser.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    init = commands.add_parser("init")
    init_where = init.add_mutually_exclusive_group(required=True)
    init_where.add_argument("--config", type=pathlib.PurePath)
    init_where.add_argument("--config-json", action="store_true", dest="config_json")
    init.add_argument("--run-dir", type=str, default="")
```

`required=True` on both groups is Review Focus item 4. Without it, omitting both leaves
`args.config` as `None`.

Add one function that both commands use, so the choice of source is made in exactly one place:

```python
def _chosen_config(config_path: pathlib.PurePath | None, fs: FileSystem) -> Config:
    if config_path is None:
        return config_from_json(document_on_stdin(sys.stdin), fs)
    return load_config(config_path, fs)
```

Then change the two command bodies:

```python
def init_command(config_path: pathlib.PurePath | None, run_dir: str) -> int:
    fs = RealFileSystem()
    config = _chosen_config(config_path, fs)
    sys.stdout.write(f"{created_run_dir(run_dir, config.home, SystemClock(), fs)}\n")
    return 0


def main(config_path: pathlib.PurePath | None, run_dir: pathlib.PurePath) -> int:
    logging.basicConfig(level=logging.INFO)
    fs = RealFileSystem()
    config = _chosen_config(config_path, fs)
    try:
        produced = run(config, run_dir, SystemClock(), fs)
    except NoOutcome as exc:
        LOGGER.error("%s", exc)
        return 1
    sys.stdout.write(produced.model_dump_json() + "\n")
    return 0
```

`args.config` is `None` when `--config-json` was given, because the group is mutually exclusive
and `--config` has no default. The `| None` in the two signatures is the argparse boundary, not a
`None` creeping into the domain — `_chosen_config` resolves it immediately and everything below
takes a `Config`.

`fork` and `watch` are untouched. Their `--config` arguments keep `required=True` as they are.

- [ ] **Step 10: Run the unit suite**

Run: `uv run pytest tests/unit -v`

Expected: PASS. Then check the argparse behaviour by hand, since it is the one thing no unit test covers:

```bash
uv run ancalagon run --run-dir /tmp/x 2>&1 | head -3
```

Expected: a usage error naming `--config` and `--config-json` as required, exit status 2.

- [ ] **Step 11: Write the integration test**

Create `tests/integration/test_config_on_stdin.py`. This mirrors
`test_pipeline_spawns_a_worker_and_records_its_failure_without_a_model` in
`tests/integration/test_end_to_end.py:125` — the ungated one that names a nonexistent model, so it
needs no network and still drives the whole pipeline. It proves the config arrived, the run
directory was allocated from `config.home`, a worker was spawned and an outcome was written. What
the worker then did with a bogus model is not this test's subject.

```python
import json
import os
import pathlib
import subprocess
import sys

from ancalagon.attempt.closed import Closed
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.fs.real_file_system import RealFileSystem

BEHAVIOUR = "You answer the question you are given."


def _document(base: pathlib.Path) -> str:
    return json.dumps(
        {
            "base": str(base),
            "workspace": {
                "home": "./ws",
                "write_roots": [],
                "read_roots": ["./artifacts"],
            },
            "model": {
                "name": "no-such-provider/no-such-model",
                "num_retries": 1,
                "request_timeout_s": 30,
                "max_tokens": 1000,
                "allowed_domains": [],
            },
            "limits": {
                "max_concurrent_agents": 1,
                "agent_timeout_s": 120,
                "max_depth": 0,
                "compact_above_tokens": 60000,
                "keep_recent_messages": 8,
                "summary_chars": 1000,
            },
            "sandbox": {"strategy": "none"},
            "roles": {
                "root": {
                    "behaviour": BEHAVIOUR,
                    "tools": ["read_file", "submit_answer"],
                    "budget": {"turns": 2, "tool_calls": 4},
                }
            },
            "run": {"goal_file": "./goal.md", "input_file": "", "role": "root"},
        }
    )


def _cli(document: str, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ancalagon.cli", *argv],
        input=document,
        capture_output=True,
        text=True,
        timeout=300,
        env=dict(os.environ),
    )


def test_a_run_is_driven_entirely_from_a_document_on_stdin(tmp_path: pathlib.Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "goal.md").write_text("Say hello.")
    document = _document(tmp_path)

    started = _cli(document, "init", "--config-json")
    assert started.returncode == 0, started.stderr
    allocated = started.stdout.strip()

    migrated = _cli("", "migrate", "--db", f"{allocated}/bus.db")
    assert migrated.returncode == 0, migrated.stderr

    completed = _cli(document, "run", "--config-json", "--run-dir", allocated)
    assert completed.returncode == 0, completed.stderr

    assert list((tmp_path / "ws" / "runs").iterdir()) == [pathlib.Path(allocated)]
    task_dir = pathlib.Path(allocated) / "tasks" / "root"
    assert json.loads((task_dir / "spec.json").read_text())["role"]["behaviour"] == BEHAVIOUR

    outcome = json.loads((task_dir / "outcome-1.json").read_text())
    assert outcome["kind"] == "failed"

    bus = LifecycleStore.open(
        pathlib.Path(allocated) / "bus.db", SystemClock(), RealFileSystem()
    )
    assert bus.attempt(1) == Closed(verdict=AgentStatus.FAILED)


def test_a_run_dir_allocated_from_one_document_is_reused_by_the_next_spawn(
    tmp_path: pathlib.Path,
):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "goal.md").write_text("Say hello.")
    document = _document(tmp_path)

    first = _cli(document, "init", "--config-json")
    second = _cli(document, "init", "--config-json", "--run-dir", first.stdout.strip())

    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == first.stdout.strip()
```

The `assert list(...iterdir()) == [pathlib.Path(allocated)]` line is the one that pins Review Focus
item 5's mechanism: the run directory `init` printed is the one under the `config.home` the document
named, so `run` reading `config.home` again finds it. `sandbox.strategy` is `"none"` because the
fence would need the model endpoint in `allowed_domains`, and this test has no endpoint.

`max_depth` is `0`, which forbids delegation — deliberate, since `root` names no `delegate_*` tool.
`migrate` takes no document, so it is passed `""`; its stdin is never read.

- [ ] **Step 12: Run the integration suite whole**

Run: `uv run pytest tests/integration`

Expected: PASS, all of it. Not `-k stdin`. Two plans in a row narrowed this step and both let a regression reach review.

- [ ] **Step 13: Update the living documentation**

In `README.md`, extend the paragraph at line 102 that currently reads "A `Config` comes from
`load_config` for a TOML file, from `Config.model_validate_json` for a JSON one, or from Python
directly". It is about the in-process seam and stays accurate; add the out-of-process route beside
it, and a short subsection showing the three spawns with the document on stdin. State the two
things a caller must get right:

- `base` is absolute and is the directory its relative paths and dotted module refs resolve against.
- The **same document** goes to `init` and to `run`. `init` allocates the run directory under
  `config.home` and `run` reads `config.home` again; if they disagree the run directory is outside
  the home and the first tool that writes raises `ScopeError`. This is Review Focus item 5 and the
  README is where it gets pinned, next to the three existing "fail later than you would like" notes.

In `docs/architecture.md`, line 69 says "`main` calls `config/load.py`, which reads the TOML."
Update it to name both readers and the shared `from_raw.py`, keeping the sentence about relative
roots resolving against the config file rather than the process cwd — which is now "against the
file, or against the document's `base`".

- [ ] **Step 14: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

```bash
git add ancalagon/config/from_json.py ancalagon/cli.py tests/unit/test_config_from_json.py tests/integration/test_config_on_stdin.py README.md docs/architecture.md
git commit -m "Take a whole config as JSON on stdin

A caller that generates its settings had to either import ancalagon or
template a TOML file. --config-json on run and init reads the same
document RawConfig already states, from stdin, so a caller in any
language can start a run without taking the dependency.

A document has no location, so it states its base: the absolute
directory its relative paths and dotted refs resolve against.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `ancalagon schema`

Separately revertible. The JSON route works without this; it is what makes the contract findable instead of reverse-engineered from error messages.

**Files:**
- Create: `ancalagon/schema_command.py`
- Modify: `ancalagon/cli.py`
- Modify: `README.md`, `pyproject.toml` (layers contract)
- Test: `tests/unit/test_schema_command.py`

**Interfaces:**
- Consumes: `RawConfig` from Task 1.
- Produces: `schema_command(out: typing.TextIO) -> int` in `ancalagon.schema_command`; the `schema` subcommand.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_schema_command.py`:

```python
import io
import json

from ancalagon.schema_command import schema_command


def test_the_schema_names_every_required_table_and_the_role_shape():
    out = io.StringIO()

    assert schema_command(out) == 0

    schema = json.loads(out.getvalue())
    assert sorted(schema["required"]) == [
        "limits",
        "model",
        "run",
        "sandbox",
        "workspace",
    ]
    assert "RawRole" in schema["$defs"]
    assert schema["$defs"]["Strategy"]["enum"] == ["none", "fence"]
    assert "absolute" in schema["properties"]["base"]["description"]
```

The `required` assertion is the one that matters: it is the list of tables a document must carry,
and it fails if a field in Task 1 gains a default it should not have. The `base` description
assertion ties the constraint to the thing the caller reads.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_schema_command.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.schema_command'`.

- [ ] **Step 3: Write the command**

Create `ancalagon/schema_command.py`:

```python
# Writes the config document's JSON Schema, for callers that generate one.
import json
import typing

from ancalagon.config.raw_config import RawConfig


def schema_command(out: typing.TextIO) -> int:
    out.write(json.dumps(RawConfig.model_json_schema(), indent=2) + "\n")
    return 0
```

`json.dumps` here is a boundary write to a stream, the same as `main`'s `model_dump_json` — not a
JSON value carried through a pipeline.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_schema_command.py -v`

Expected: PASS. If `Strategy`'s enum order differs, assert `sorted(...)` on it rather than changing `Strategy`.

- [ ] **Step 5: Wire the CLI**

In `ancalagon/cli.py`, add `commands.add_parser("schema")` beside the others, the import, and the dispatch:

```python
        if args.command == "schema":
            return schema_command(sys.stdout)
```

`schema` takes no arguments.

- [ ] **Step 6: Add the layers contract entry**

`pyproject.toml`'s "Layers point downward" contract lists each top-level module. Add
`ancalagon.schema_command` to it, at the same level as `ancalagon.trace` and
`ancalagon.viz` — above `ancalagon.config`, which it imports, and below `ancalagon.cli`, which
imports it.

Run: `uv run lint-imports`

Expected: all seven contracts kept.

- [ ] **Step 7: Document it**

In `README.md`, add `ancalagon schema` to the JSON-route subsection Task 2 added: one line saying
it writes the document's JSON Schema to stdout, and that a caller generates and validates against
it rather than reading `ancalagon.example.toml` prose.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

```bash
git add ancalagon/schema_command.py ancalagon/cli.py tests/unit/test_schema_command.py pyproject.toml README.md
git commit -m "Print the config document's schema

A caller generating JSON had nothing to build against but
ancalagon.example.toml prose. ancalagon schema writes RawConfig's JSON
Schema, so a caller in any language can generate a document and validate
it before spawning.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Ordering

Task 1 lands alone, before Task 2 is started. If both arrive together a reviewer cannot tell a
resolution bug from a reader bug, which is the whole reason the seam is worth cutting first.

Task 3 depends only on Task 1's `RawConfig` and could land before Task 2, but the README section it
extends is written in Task 2, so keep the order.
