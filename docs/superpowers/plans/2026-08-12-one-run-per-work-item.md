# One Run Per Work Item Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an external driver invoke one ancalagon run per item in a large population, cheaply and resumably.

**Architecture:** Two independent changes. The system prompt becomes a cache-marked wire block so the static prefix is not re-billed every turn. A required `[run]` section in the TOML carries the three things a driver varies per item — where the run lives, where its goal text is, and what shape it must answer in — replacing the fixed `FreeText` contract, the argv-only goal, and the always-fresh `r_NNNN` directory.

**Tech Stack:** Python 3.13, pydantic, tomllib, litellm, pytest, pyright strict, black.

## Global Constraints

- Pyright strict must pass with zero errors: `uv run pyright`.
- `Any` and `object` annotations are banned, as are `JsonValue`/`JsonDict`/hand-rolled JSON aliases. Enforced by `precommit-scripts/check-type-hygiene`.
- Every generic must be parameterised: `dict[str, str]`, never bare `dict`.
- One class per module.
- No comments except a single one-line header on a module or class. No docstrings.
- Black, `line-length = 100`, `target-version = ["py313"]`.
- Few tests, each covering a whole behaviour, asserting everything that behaviour implies.
- **Nothing in this repository may name or hint at any specific downstream user of the harness** — no domain vocabulary, program names, field names, identifiers or prompt text belonging to a consuming project. Test fixtures use neutral placeholders. Enforced by the `terminology-guard` pre-commit hook against `~/.config/git/blocklist.txt`, on both file content and commit messages.
- Never `--no-verify`. The hooks run black and `git add -u`, so re-check `git diff --cached --name-only` after a blocked commit.
- Talisman flags "Potential secret pattern" on the word `pass` and on the `key` inside `monkeypatch`, so a test-heavy diff will be blocked. Fix it in `.talismanrc`: `git add` the file first, because `talisman --checksum=<path>` hashes the **staged** blob and silently returns the previous value otherwise; then replace that file's line, or **append** if it has none. Entries exist for `ancalagon/config/load.py` and `tests/unit/test_llm_adapter.py` and both are modified here, so both need the new value. Never `shasum`, never overwrite an unrelated entry, never `--no-verify`.
- Unit suite: `uv run pytest tests/unit -x -q`. Integration suite: `uv run pytest tests/integration`.

---

## File Structure

| File | Responsibility |
|---|---|
| `ancalagon/llm/adapters/wire_text_block.py` | **create** — one text block in wire format, optionally cache-marked |
| `ancalagon/llm/adapters/wire_message.py` | **modify** — `content` widens to accept blocks |
| `ancalagon/llm/adapters/litellm_client.py` | **modify** — build the system message as one cache-marked block |
| `ancalagon/contracts/run_settings.py` | **create** — what one run varies from every other |
| `ancalagon/config/config.py` | **modify** — carry `RunSettings` |
| `ancalagon/config/load.py` | **modify** — read and resolve `[run]` |
| `ancalagon/cli.py` | **modify** — four pure helpers plus assembly in `main` |
| `ancalagon.example.toml` | **modify** — ship the `[run]` block |
| `README.md`, `docs/architecture.md` | **modify** — describe the new invocation |
| `tests/unit/test_llm_adapter.py` | **modify** — assert the cache-marked system block |
| `tests/unit/test_config_load.py` | **create** — `[run]` resolution and required-ness |
| `tests/unit/test_cli_settings.py` | **create** — the four helpers |
| `tests/integration/test_end_to_end.py` | **modify** — `[run]` in the fixture; a second invocation reuses the directory |

---

### Task 1: The system prompt is one cache-marked block

**Files:**
- Create: `ancalagon/llm/adapters/wire_text_block.py`
- Modify: `ancalagon/llm/adapters/wire_message.py`
- Modify: `ancalagon/llm/adapters/litellm_client.py:56` (the `wire` list) and its imports
- Test: `tests/unit/test_llm_adapter.py`

**Interfaces:**
- Consumes: `Message`, `Role`, `Text`, `ToolSchema`, `LiteLLMClient`, `to_wire` — all unchanged.
- Produces: `WireTextBlock(type: str, text: str, cache_control: dict[str, str])`. `WireMessage.content: str | tuple[WireTextBlock, ...]`. `to_wire` still returns string content for every non-system message.

`type` and `text` are **required, not defaulted**. The payload is dumped with `exclude_defaults=True`, so a field equal to its default disappears — a defaulted `type = "text"` would be dropped and the provider would reject the block.

The spec's "the tool schemas precede it" is not assertable here: `tools` is a separate keyword argument to `litellm.completion`, not part of `messages`, and the order the provider renders them in is the provider's. Assert the block's shape and that the schemas still pass through.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_llm_adapter.py`. It needs one import added at the top: `from ancalagon.llm.tool_schema import ToolSchema`.

```python
def test_the_system_prompt_is_sent_as_one_cache_marked_block(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[list[WireDict]] = []

    class FakeMessage:
        content = "done"
        tool_calls: list[str] = []

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeResponse:
        choices = [FakeChoice()]

    def fake_completion(
        model: str,
        messages: list[WireDict],
        tools: list[dict[str, str]],
        max_tokens: int,
        num_retries: int,
        timeout: int,
        tool_choice: str | dict[str, str | dict[str, str]],
    ) -> FakeResponse:
        seen.append(messages)
        return FakeResponse()

    fake = types.ModuleType("litellm")
    setattr(fake, "completion", fake_completion)
    setattr(fake, "ModelResponse", FakeResponse)
    monkeypatch.setitem(sys.modules, "litellm", fake)

    user = Message(role=Role.USER, blocks=[Text(text="the item")], agent=1, seq=0, ts="")
    client = LiteLLMClient(model="m", max_tokens=10, num_retries=1, request_timeout_s=9)
    client.complete(
        "behave", [user], [ToolSchema(name="rg", description="d", parameters_json="{}")]
    )

    assert seen[0][0] == {
        "role": "system",
        "content": [
            {"type": "text", "text": "behave", "cache_control": {"type": "ephemeral"}}
        ],
    }
    assert seen[0][1] == {"role": "user", "content": "the item"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_llm_adapter.py::test_the_system_prompt_is_sent_as_one_cache_marked_block -x -q`
Expected: FAIL — the system message's `content` is the string `"behave"`, not a list of blocks.

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/llm/adapters/wire_text_block.py`:

```python
# One text block in provider wire format, optionally marked as a prompt-cache breakpoint.
import pydantic


class WireTextBlock(pydantic.BaseModel, frozen=True):
    type: str
    text: str
    cache_control: dict[str, str] = {}
```

Modify `ancalagon/llm/adapters/wire_message.py`:

```python
# One message in provider wire format, typed so the payload never becomes an untyped dict.
import pydantic

from ancalagon.llm.adapters.wire_text_block import WireTextBlock
from ancalagon.llm.adapters.wire_tool_call import WireToolCall


class WireMessage(pydantic.BaseModel, frozen=True):
    role: str
    content: str | tuple[WireTextBlock, ...] = ""
    tool_calls: list[WireToolCall] = []
    tool_call_id: str = ""
```

In `ancalagon/llm/adapters/litellm_client.py`, add the import and a module constant, then replace the one line that builds the system message:

```python
from ancalagon.llm.adapters.wire_text_block import WireTextBlock

EPHEMERAL = {"type": "ephemeral"}
```

```python
        wire = [
            WireMessage(
                role="system",
                content=(WireTextBlock(type="text", text=system, cache_control=EPHEMERAL),),
            )
        ]
```

- [ ] **Step 4: Run the whole unit suite**

Run: `uv run pytest tests/unit -x -q`
Expected: PASS, including the pre-existing `test_wire_format_preserves_tool_calls_and_passes_retry_settings` — `to_wire` was not touched, so every non-system message still carries string content.

- [ ] **Step 5: Type-check**

Run: `uv run pyright`
Expected: 0 errors. If it complains where `content` is read as a string, the reader must narrow with `isinstance`; do not widen a signature to silence it.

- [ ] **Step 6: Commit**

```bash
git add ancalagon/llm/adapters/wire_text_block.py ancalagon/llm/adapters/wire_message.py ancalagon/llm/adapters/litellm_client.py tests/unit/test_llm_adapter.py
git commit -m "Send the system prompt as a cache-marked block so a turn stops re-billing it"
```

---

### Task 2: A `[run]` section every config file must carry

**Files:**
- Create: `ancalagon/contracts/run_settings.py`
- Modify: `ancalagon/config/config.py`
- Modify: `ancalagon/config/load.py`
- Modify: `ancalagon.example.toml`
- Test: `tests/unit/test_config_load.py` (create), `tests/integration/test_end_to_end.py` (fixture only)

**Interfaces:**
- Consumes: `Config`, `load_config`, `_root` from `config/load.py`.
- Produces: `RunSettings(run_dir: str, goal_file: str, contract_module: str, contract_class: str)`, all defaulting to `""`. `Config.run: RunSettings`. Paths arrive **already resolved to absolute strings**; `contract_class` is the bare class name.

Paths are held as `str`, not `pathlib.Path`, because the house null object for an absent value is the empty string and `pathlib.Path("")` is `PosixPath(".")` — a truthy, valid directory that would silently mean "here".

`contract` is either empty or has both halves. `load_config` rejects `"shape.py"` with no class, so `contract_module` is empty exactly when `contract_class` is.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_config_load.py`:

```python
import pathlib

import pytest

from ancalagon.config.load import load_config

TEMPLATE = """
[workspace]
write_root = "./ws"
read_roots = ["./artifacts"]

[agent]
root_behaviour = "You investigate."

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000

[budget]
turns = 4
tool_calls = 8

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[tools]
enabled = []
{run}
"""


def _config_file(tmp_path: pathlib.Path, name: str, run: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(TEMPLATE.format(run=run))
    return path


def test_run_settings_resolve_against_the_config_file(tmp_path: pathlib.Path):
    path = _config_file(
        tmp_path,
        "populated.toml",
        '[run]\nrun_dir = "./ws/runs/item"\ngoal_file = "./goal.md"\n'
        'contract = "./shape.py:Answer"\n',
    )

    settings = load_config(path).run

    assert settings.run_dir == str(tmp_path / "ws" / "runs" / "item")
    assert settings.goal_file == str(tmp_path / "goal.md")
    assert settings.contract_module == str(tmp_path / "shape.py")
    assert settings.contract_class == "Answer"


def test_the_run_section_is_required_and_a_contract_must_name_a_class(
    tmp_path: pathlib.Path,
):
    blank = _config_file(
        tmp_path, "blank.toml", '[run]\nrun_dir = ""\ngoal_file = ""\ncontract = ""\n'
    )
    settings = load_config(blank).run
    assert (settings.run_dir, settings.goal_file, settings.contract_module) == ("", "", "")
    assert settings.contract_class == ""

    with pytest.raises(KeyError):
        load_config(_config_file(tmp_path, "absent.toml", ""))

    with pytest.raises(KeyError):
        load_config(
            _config_file(tmp_path, "partial.toml", '[run]\nrun_dir = ""\ngoal_file = ""\n')
        )

    with pytest.raises(ValueError):
        load_config(
            _config_file(
                tmp_path,
                "classless.toml",
                '[run]\nrun_dir = ""\ngoal_file = ""\ncontract = "./shape.py"\n',
            )
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_load.py -x -q`
Expected: FAIL — `Config` has no attribute `run`.

- [ ] **Step 3: Write minimal implementation**

Create `ancalagon/contracts/run_settings.py`:

```python
# What one run varies from every other: where it lives, where its goal is, what shape it answers in.
import pydantic


class RunSettings(pydantic.BaseModel, frozen=True):
    run_dir: str = ""
    goal_file: str = ""
    contract_module: str = ""
    contract_class: str = ""
```

In `ancalagon/config/config.py`, add the import and the field:

```python
from ancalagon.contracts.run_settings import RunSettings
```

```python
    run: RunSettings = RunSettings()
```

In `ancalagon/config/load.py`, add the import, two helpers, and the field:

```python
from ancalagon.contracts.run_settings import RunSettings
```

```python
def _optional_root(base: pathlib.Path, value: str) -> str:
    return str(_root(base, value)) if value else ""


def _run_settings(base: pathlib.Path, run: dict[str, str]) -> RunSettings:
    module, _, class_name = run["contract"].partition(":")
    if run["contract"] and not (module and class_name):
        raise ValueError(f'contract "{run["contract"]}" must be written path.py:ClassName')
    return RunSettings(
        run_dir=_optional_root(base, run["run_dir"]),
        goal_file=_optional_root(base, run["goal_file"]),
        contract_module=_optional_root(base, module),
        contract_class=class_name,
    )
```

and inside the `Config(...)` call:

```python
        run=_run_settings(base, raw["run"]),
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/unit/test_config_load.py -x -q`
Expected: PASS.

- [ ] **Step 5: Add `[run]` to the shipped example**

Append to `ancalagon.example.toml`:

```toml
[run]
run_dir = ""    # where this run lives; empty allocates the next write_root/runs/r_NNNN
goal_file = ""  # empty means the goal comes from --goal
contract = ""   # "path.py:ClassName"; empty means FreeText
```

- [ ] **Step 6: Add `[run]` to the integration fixture**

In `tests/integration/test_end_to_end.py`, give `_config` a `run_dir` parameter and emit the section. Replace the signature and append to the written TOML:

```python
def _config(
    tmp_path: pathlib.Path,
    turns: int,
    tool_calls: int,
    model: str = "",
    run_dir: str = "",
) -> pathlib.Path:
```

```python
[tools]
enabled = []

[run]
run_dir = "{run_dir}"
goal_file = ""
contract = ""
""")
```

- [ ] **Step 7: Run both suites**

Run: `uv run pytest tests/unit -x -q && uv run pytest tests/integration -q && uv run pyright`
Expected: PASS, 0 pyright errors. `tests/unit/test_tools.py` and `tests/unit/test_workspace_scoping.py` build `Config` in code and are unaffected — `run` defaults.

- [ ] **Step 8: Commit**

```bash
git add ancalagon/contracts/run_settings.py ancalagon/config/config.py ancalagon/config/load.py ancalagon.example.toml tests/unit/test_config_load.py tests/integration/test_end_to_end.py
git commit -m "Carry the three per-run settings in the config file, required like every other"
```

---

### Task 3: The CLI honours the run settings

**Files:**
- Modify: `ancalagon/cli.py`
- Test: `tests/unit/test_cli_settings.py` (create)

**Interfaces:**
- Consumes: `RunSettings` and `Config.run` from Task 2; `FREE_TEXT_MODULE`.
- Produces, all importable from `ancalagon.cli`:
  - `run_dir_of(settings: RunSettings, write_root: pathlib.Path) -> pathlib.Path` — creates and returns the directory
  - `goal_of(settings: RunSettings, given: str) -> str` — raises `ValueError` on both or neither
  - `output_of(settings: RunSettings) -> str` — `"contracts.py:FreeText"` or `"contracts.py:<class>"`
  - `contract_source(settings: RunSettings) -> str` — `FREE_TEXT_MODULE` or the named module's text
- `main(config_path, goal_argument)` keeps its two-argument shape; `--goal` is no longer required and defaults to `""`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_settings.py`:

```python
import pathlib

import pytest

from ancalagon.cli import contract_source, goal_of, output_of, run_dir_of
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.contracts.run_settings import RunSettings


def test_a_named_run_dir_is_used_verbatim_and_an_unnamed_one_is_allocated(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    named = tmp_path / "units" / "abc123"

    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named
    assert named.is_dir()
    assert run_dir_of(RunSettings(run_dir=str(named)), write_root) == named

    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0001"
    assert run_dir_of(RunSettings(), write_root) == write_root / "runs" / "r_0002"


def test_a_goal_comes_from_exactly_one_of_the_file_and_the_argument(
    tmp_path: pathlib.Path,
):
    goal_file = tmp_path / "goal.md"
    goal_file.write_text("describe the item")

    assert goal_of(RunSettings(goal_file=str(goal_file)), "") == "describe the item"
    assert goal_of(RunSettings(), "inline") == "inline"

    with pytest.raises(ValueError):
        goal_of(RunSettings(goal_file=str(goal_file)), "inline")
    with pytest.raises(ValueError):
        goal_of(RunSettings(), "")


def test_a_named_contract_replaces_free_text(tmp_path: pathlib.Path):
    module = tmp_path / "shape.py"
    module.write_text(
        "import pydantic\n\n\nclass Answer(pydantic.BaseModel):\n    verdict: str\n"
    )

    assert output_of(RunSettings()) == "contracts.py:FreeText"
    assert contract_source(RunSettings()) == FREE_TEXT_MODULE

    named = RunSettings(contract_module=str(module), contract_class="Answer")
    assert output_of(named) == "contracts.py:Answer"
    assert "class Answer" in contract_source(named)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli_settings.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'run_dir_of' from 'ancalagon.cli'`.

- [ ] **Step 3: Write minimal implementation**

In `ancalagon/cli.py`, add imports and the constant:

```python
from ancalagon.contracts.run_settings import RunSettings

FREE_TEXT_OUTPUT = "contracts.py:FreeText"
```

Replace `_new_run_dir` with an allocator plus the four helpers:

```python
def _allocated_run_dir(write_root: pathlib.Path) -> pathlib.Path:
    runs = write_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[2:]) for p in runs.glob("r_*") if p.name[2:].isdigit()]
    return runs / f"r_{max(existing, default=0) + 1:04d}"


def run_dir_of(settings: RunSettings, write_root: pathlib.Path) -> pathlib.Path:
    chosen = (
        pathlib.Path(settings.run_dir) if settings.run_dir else _allocated_run_dir(write_root)
    )
    chosen.mkdir(parents=True, exist_ok=True)
    return chosen


def goal_of(settings: RunSettings, given: str) -> str:
    if settings.goal_file and given:
        raise ValueError("a goal came from both --goal and [run] goal_file; give one")
    if settings.goal_file:
        return pathlib.Path(settings.goal_file).read_text()
    if given:
        return given
    raise ValueError("no goal: pass --goal or set [run] goal_file")


def output_of(settings: RunSettings) -> str:
    if not settings.contract_class:
        return FREE_TEXT_OUTPUT
    return f"contracts.py:{settings.contract_class}"


def contract_source(settings: RunSettings) -> str:
    if not settings.contract_module:
        return FREE_TEXT_MODULE
    return pathlib.Path(settings.contract_module).read_text()
```

Rewrite the head of `main` — note `exist_ok=True` on the task directory, without which a second invocation at the same `run_dir` dies with `FileExistsError`:

```python
def main(config_path: pathlib.Path, goal_argument: str) -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config(config_path)
    goal = goal_of(config.run, goal_argument)
    run_dir = run_dir_of(config.run, config.write_root)
    task_dir = run_dir / "tasks" / "root"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "contracts.py").write_text(contract_source(config.run))
    (task_dir / "spec.json").write_text(
        json.dumps(
            {
                "task_id": "root",
                "behaviour": config.root_behaviour,
                "goal": goal,
                "input": {"text": goal},
                "output": output_of(config.run),
                "budget": {
                    "turns": config.budget.turns,
                    "tool_calls": config.budget.tool_calls,
                },
                "tools": [],
            }
        )
    )
```

Everything from `bus = Bus.open(...)` onward is unchanged.

Make `--goal` optional and report a bad combination without a traceback:

```python
def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--goal", type=str, default="")
    args = parser.parse_args()
    try:
        return main(args.config, args.goal)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/unit/test_cli_settings.py -x -q`
Expected: PASS.

- [ ] **Step 5: Run everything**

Run: `uv run pytest tests/unit -x -q && uv run pytest tests/integration -q && uv run pyright`
Expected: PASS, 0 errors. The existing integration test passes `--goal` with an empty `[run]`, which is still the valid inline path.

- [ ] **Step 6: Commit**

```bash
git add ancalagon/cli.py tests/unit/test_cli_settings.py
git commit -m "Take the run directory, the goal and the output contract from the config"
```

---

### Task 4: A second invocation continues the first, and the docs say so

**Files:**
- Modify: `tests/integration/test_end_to_end.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3. Nothing new is produced.

This test needs no credential: the model is `no-such-provider/no-such-model`, both attempts crash, and what is asserted is that the *directory and task row were reused* — one task, two agents — rather than a second run being allocated.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_end_to_end.py`:

```python
def test_a_named_run_dir_is_reused_by_a_second_invocation(tmp_path: pathlib.Path):
    named = tmp_path / "ws" / "runs" / "item-0001"
    config = _config(
        tmp_path,
        turns=2,
        tool_calls=4,
        model="no-such-provider/no-such-model",
        run_dir=str(named),
    )

    first = _run_cli(config, "Say hello.", dict(os.environ))
    assert first.returncode == 0, first.stderr
    second = _run_cli(config, "Say hello.", dict(os.environ))
    assert second.returncode == 0, second.stderr

    assert [p.name for p in (tmp_path / "ws" / "runs").iterdir()] == ["item-0001"]

    bus = Bus.open(named / "bus.db")
    assert bus.state(1).status is AgentStatus.CRASHED
    assert bus.state(2).status is AgentStatus.CRASHED
    assert len(list((named / "tasks" / "root").glob("stderr-*.log"))) == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/test_end_to_end.py::test_a_named_run_dir_is_reused_by_a_second_invocation -x -q`
Expected: PASS once Task 3 is in. If it fails, the likely causes in order are: `task_dir.mkdir` missing `exist_ok=True`; `_config` not emitting the `run_dir` value; the second `bus.state(2)` absent because `enqueue` created a second task row rather than reusing the one keyed on `dir`.

Write it before Task 3 if executing strictly in order, and confirm it fails with `FileExistsError` in `second.stderr`.

- [ ] **Step 3: Update the README**

In `README.md`, under `## Running`, after the existing `uv run ancalagon run` block, add:

```markdown
A driver running one item at a time sets the per-run values in the config instead:

```toml
[run]
run_dir = "./ws/units/abc123"    # reused on a second invocation, which continues the transcript
goal_file = "./ws/units/abc123/goal.md"
contract = "./shape.py:Answer"   # the root answers in this shape, not free text
```

`--goal` and `goal_file` are alternatives; give exactly one. An empty `run_dir` allocates the next
`runs/r_NNNN` as before.
```

- [ ] **Step 4: Update the architecture trace**

In `docs/architecture.md`, section `### 1. Starting a run`, replace items 2 and 3 so the trace stays accurate:

```markdown
2. `run_dir_of` uses `[run] run_dir` when set and allocates `<write_root>/runs/r_NNNN` when not,
   creating either. A directory that already holds a task is reused, which is what makes a
   second invocation continue rather than start over.
3. Writes two files into `runs/<run>/tasks/root/`: `contracts.py` — `[run] contract`'s module when
   named, otherwise `contracts/free_text_module.py` — and `spec.json` naming the class it must
   answer in. The goal comes from `[run] goal_file` or `--goal`; exactly one.
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest tests/unit -x -q && uv run pytest tests/integration -q && uv run pyright`
Expected: PASS, 0 errors.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_end_to_end.py README.md docs/architecture.md
git commit -m "Prove a reused run directory continues one task, and document the shape"
```

---

## Deferred

Per-turn caching of the growing transcript. Any content-addressed cache of model calls.

Two live checks, not code changes, for whoever first runs against a real endpoint: that the breakpoint took effect rather than being silently ignored for falling under the minimum cacheable prefix — read `cache_creation_input_tokens` and `cache_read_input_tokens` from the response `usage`, which `LiteLLMClient` does not currently surface; and whether `thinking: {"type": "disabled"}` is required alongside a forced `tool_choice` on a partner-operated endpoint.
