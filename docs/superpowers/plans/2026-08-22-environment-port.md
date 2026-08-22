# Environment Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the process environment behind a port so a spawned worker inherits a value the harness chose, not whatever the launching shell happened to hold.

**Architecture:** An `Environment` protocol in a new leaf package `ancalagon/env/`, with `RealEnvironment` wrapping `os.environ` and `FakeEnvironment` fixed at construction. `SubprocessSpawner` — the only reader of `os.environ` in the package — takes one at construction. A precommit ripgrep script bans `os.environ` and `os.getenv` outside the adapter, and an import-linter layer keeps the package a leaf.

**Tech Stack:** Python 3.13, `typing.Protocol`, pytest, import-linter, a bash + ripgrep precommit script.

**Spec:** `docs/superpowers/specs/2026-08-22-ports-for-filesystem-and-environment-design.md` — this plan implements the `Environment` half only. The `FileSystem` half is a separate plan and must not be started here.

## Global Constraints

- Pyright strict, **zero errors**. `Any` and `object` are banned outright; every generic is parameterised.
- **No comments** except a one-line header on a class or module.
- Fakes live beside their port in the package, following `ancalagon/clock/fake_clock.py`, `ancalagon/llm/fake_llm.py` and `ancalagon/supervisor/fake_liveness.py`.
- A class implementing a `Protocol` **inherits** it, so the error lands on the broken class.
- Dataclasses are `frozen=True`. No `None` defaults, no `None` returns, no defensive guards, no bare `except`.
- No mocking. `pytest`'s `monkeypatch` is permitted for environment variables; `unittest.mock` is not.
- Few tests, each covering a whole behaviour.
- Never name an external codebase under analysis in any tracked artifact.
- **There is no bypass for the pre-commit hooks.** Never `git stash`.
- Verify with: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`.
- Test counts before this plan: **83 unit**, **10 integration passed / 2 skipped**. Tasks 1 and 2 each add one unit test; nothing else moves.

---

### Task 1: The port, its adapter, and its fake

**Files:**
- Create: `ancalagon/env/environment.py`
- Create: `ancalagon/env/real_environment.py`
- Create: `ancalagon/env/fake_environment.py`
- Test: `tests/unit/test_environment.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Environment` (protocol, method `variables() -> collections.abc.Mapping[str, str]`), `RealEnvironment()`, `FakeEnvironment(variables: collections.abc.Mapping[str, str] = {})`. Task 2 injects these into `SubprocessSpawner`.

`ancalagon/env/` gets no `__init__.py` — no package in `ancalagon/` has one.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_environment.py`:

```python
import pytest

from ancalagon.env.fake_environment import FakeEnvironment
from ancalagon.env.real_environment import RealEnvironment


def test_the_real_environment_reports_the_process_and_the_fake_reports_only_what_it_was_given(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ANCALAGON_PORT_MARKER", "present")
    assert RealEnvironment().variables()["ANCALAGON_PORT_MARKER"] == "present"

    monkeypatch.delenv("ANCALAGON_PORT_MARKER")
    assert "ANCALAGON_PORT_MARKER" not in RealEnvironment().variables()

    assert FakeEnvironment({"PATH": "/bin"}).variables() == {"PATH": "/bin"}
    assert FakeEnvironment().variables() == {}
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m pytest tests/unit/test_environment.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.env'`

- [ ] **Step 3: Write the protocol**

Create `ancalagon/env/environment.py`:

```python
# The process environment a spawned child inherits, injected so it can be curated.
import collections.abc
import typing


class Environment(typing.Protocol):
    def variables(self) -> collections.abc.Mapping[str, str]: ...
```

- [ ] **Step 4: Write the adapter**

Create `ancalagon/env/real_environment.py`:

```python
# The only place in the codebase that reads the process environment.
import collections.abc
import os

from ancalagon.env.environment import Environment


class RealEnvironment(Environment):
    def variables(self) -> collections.abc.Mapping[str, str]:
        return dict(os.environ)
```

- [ ] **Step 5: Write the fake**

Create `ancalagon/env/fake_environment.py`:

```python
# An environment fixed at construction, so a test can say exactly what a child inherits.
import collections.abc

from ancalagon.env.environment import Environment


class FakeEnvironment(Environment):
    def __init__(self, variables: collections.abc.Mapping[str, str] = {}):
        self.given = dict(variables)

    def variables(self) -> collections.abc.Mapping[str, str]:
        return self.given
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run python -m pytest tests/unit/test_environment.py -q`
Expected: PASS, 1 test.

- [ ] **Step 7: Prove the protocol is load-bearing**

Temporarily rename `variables` to `values` in `real_environment.py` only, run `uv run pyright`, and confirm the error is reported **against `RealEnvironment`** and not against a distant call site. Restore the name. Record the observed message in the task report.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q
git add ancalagon/env tests/unit/test_environment.py
git commit -m "An environment can be asked what it holds"
```

Expected: 84 unit tests pass.

---

### Task 2: The spawner inherits what it is given

**Files:**
- Modify: `ancalagon/supervisor/subprocess_spawner.py`
- Modify: `ancalagon/cli.py:143-147` (the `SubprocessSpawner(...)` construction)
- Modify: `tests/unit/test_sandbox.py:58-66`
- Test: `tests/unit/test_sandbox.py` (extend the existing spawner test)

**Interfaces:**
- Consumes: `Environment`, `RealEnvironment`, `FakeEnvironment` from Task 1.
- Produces: `SubprocessSpawner(run_dir, config_path, environment, sandbox=UNSANDBOXED)` and a module-level `inherited(environment: Environment, sandbox: Sandbox) -> dict[str, str]`.

`environment` is a **required** parameter with no default, unlike `sandbox`, which defaults to `UNSANDBOXED`. There are only two construction sites, and an ambient default is the thing this plan exists to remove.

The merge is a module-level function rather than an inline expression so that what a child inherits can be asserted without spawning a process. `run_command.py` is the precedent for a module-level function in this codebase.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_sandbox.py`, and add `from ancalagon.env.fake_environment import FakeEnvironment` and `from ancalagon.supervisor.subprocess_spawner import inherited` to its imports:

```python
def test_a_child_inherits_the_given_environment_with_the_sandbox_overriding_it():
    ambient = FakeEnvironment({"PATH": "/bin", "MARKER": "ambient"})

    assert inherited(ambient, RecordingSandbox()) == {"PATH": "/bin", "MARKER": "set"}
    assert inherited(FakeEnvironment(), RecordingSandbox()) == {"MARKER": "set"}
    assert inherited(ambient, Unsandboxed()) == {"PATH": "/bin", "MARKER": "ambient"}
```

`RecordingSandbox` already exists in that file and its `environment()` returns `{"MARKER": "set"}`. `Unsandboxed` is already imported there; `RealEnvironment` and `FakeEnvironment` are not.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: FAIL — `ImportError: cannot import name 'inherited'`

- [ ] **Step 3: Change the spawner**

In `ancalagon/supervisor/subprocess_spawner.py`: delete `import os`, add `from ancalagon.env.environment import Environment`, add the module-level function, and take the port at construction.

```python
def inherited(environment: Environment, sandbox: Sandbox) -> dict[str, str]:
    return {**environment.variables(), **sandbox.environment()}
```

Constructor — `environment` is required, so it precedes the defaulted `sandbox`:

```python
    def __init__(
        self,
        run_dir: pathlib.Path,
        config_path: pathlib.Path,
        environment: Environment,
        sandbox: Sandbox = UNSANDBOXED,
    ):
        self.run_dir = run_dir
        self.config_path = config_path
        self.environment = environment
        self.sandbox = sandbox
```

In `spawn`, replace the `env=` argument:

```python
            env=inherited(self.environment, self.sandbox),
```

- [ ] **Step 4: Update both construction sites**

`ancalagon/cli.py` — add `from ancalagon.env.real_environment import RealEnvironment` and pass it:

```python
        spawner=SubprocessSpawner(
            run_dir=run_dir,
            config_path=config_path.resolve(),
            environment=RealEnvironment(),
            sandbox=sandbox_of(config, run_dir),
        ),
```

`tests/unit/test_sandbox.py:61` — the existing `test_the_spawner_wraps_the_worker_command_with_its_sandbox` constructs a spawner. Give it `environment=RealEnvironment()`, so that test keeps spawning a real worker with a real environment and only the new test uses the fake.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/unit -q`
Expected: PASS, 85 unit tests.

- [ ] **Step 6: Confirm `os.environ` is gone from the package**

Run: `rg -n 'os\.environ|os\.getenv' ancalagon`
Expected: exactly one hit, `ancalagon/env/real_environment.py`.

- [ ] **Step 7: Mutation-check the new test**

Break the merge in the two obvious ways and confirm the new test fails each time, then restore:
1. Reverse the merge order (`{**sandbox.environment(), **environment.variables()}`) — the sandbox override must stop winning.
2. Ignore the port (`{**os.environ, **sandbox.environment()}`) — the `FakeEnvironment()` case must stop being `{"MARKER": "set"}`.

Record both observed failures in the task report.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q
git add -A && git commit -m "A worker inherits the environment it was handed"
```

Expected: 85 unit, 10 integration passed / 2 skipped.

---

### Task 3: The layer and the ban

**Files:**
- Modify: `pyproject.toml` — the `Layers point downward` and `Sibling leaves are independent` contracts
- Create: `precommit-scripts/check-ambient-access`
- Modify: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: `ancalagon/env/` from Tasks 1 and 2.
- Produces: a precommit script the FileSystem plan will **extend** rather than replace. Name it `check-ambient-access`, not `check-environment-access`, for that reason.

- [ ] **Step 1: Add the layer**

In `pyproject.toml`, `Layers point downward` currently ends:

```toml
    "ancalagon.contracts : ancalagon.clock : ancalagon.sandbox",
    "ancalagon.migrations",
]
```

`ancalagon.env` is a leaf importing only `os`, `collections.abc` and `typing`, and `subprocess_spawner` imports it, so it goes **below** `migrations` as the new bottom layer:

```toml
    "ancalagon.contracts : ancalagon.clock : ancalagon.sandbox",
    "ancalagon.migrations",
    "ancalagon.env",
]
```

Add `"ancalagon.env"` to the `modules` list of `Sibling leaves are independent`.

- [ ] **Step 2: Add `ancalagon.env` to the SQL contract's sources**

The `SQL stays in the adapters` contract lists every package except `ancalagon.bus` and `ancalagon.migrations` in `source_modules`. A new package that is not listed is not covered. Add `"ancalagon.env"` in alphabetical position.

- [ ] **Step 3: Prove both contracts fire**

Run `uv run lint-imports` and confirm `5 kept, 0 broken` — four existing plus nothing new broken.

Then prove the layer is real: temporarily add `import ancalagon.clock.clock` to `ancalagon/env/environment.py`, run `uv run lint-imports`, and confirm `Layers point downward BROKEN` naming `ancalagon.env -> ancalagon.clock`. `env` is the **lowest** layer, so it may not import anything above it — that is the direction that breaks. Restore the file and confirm it returns to kept. Record both outputs in the task report.

- [ ] **Step 4: Write the ban**

Create `precommit-scripts/check-ambient-access`, modelled on the existing `precommit-scripts/check-type-hygiene` (read it first — match its structure, its `set -uo pipefail`, its exit-code handling and its output style):

```bash
#!/bin/bash
# Bans ambient process access outside the adapter that owns it. Pyright cannot see this:
# os.environ is a legal import everywhere, and the thing to ban is the read, not the import.

set -uo pipefail

ENV_HITS=$(rg -n --type py 'os\.environ|os\.getenv' ancalagon \
  --glob '!ancalagon/env/real_environment.py' 2>/dev/null)

STATUS=0

if [ -n "$ENV_HITS" ]; then
  echo "[ambient-access] The process environment is read outside"
  echo "                 ancalagon/env/real_environment.py. Inject an Environment and"
  echo "                 call .variables() instead."
  echo "$ENV_HITS"
  echo ""
  STATUS=1
fi

[ $STATUS -eq 0 ] && echo "[ambient-access] Clean."
exit $STATUS
```

Match `check-type-hygiene` exactly on these points: `set -uo pipefail` without `-e`, `[ -n ... ]` rather than `[[ ]]`, a `[ambient-access]` prefix on every line, a blank `echo ""` after each block, and the trailing `Clean.` line.

`chmod +x precommit-scripts/check-ambient-access`.

`tests/` is not scanned: the integration suite passes `dict(os.environ)` to `subprocess.run` deliberately, and that is correct there.

- [ ] **Step 5: Register the hook**

In `.pre-commit-config.yaml`, add after the `type-hygiene` hook, matching its shape:

```yaml
      - id: ambient-access
        name: Ban ambient environment access
        entry: precommit-scripts/check-ambient-access
        language: script
        pass_filenames: false
        files: \.py$
```

- [ ] **Step 6: Prove the ban fires**

```bash
./precommit-scripts/check-ambient-access ; echo "clean tree exit=$?"
```
Expected: exit 0, no output.

Then add `import os` and `os.environ.get("X", "")` to `ancalagon/clock/system_clock.py`, re-run, and confirm exit 1 naming that file and line. Remove it and confirm exit 0 again. Record both outputs in the task report.

- [ ] **Step 7: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run lint-imports
git add -A && git commit -m "The environment is a layer, and reading it elsewhere fails the build"
```

Expected: 85 unit, contracts `5 kept, 0 broken`, `pre-commit run ambient-access` passes.

---

## What this plan does not do

- No `FileSystem` port, no `Workspace` change, no `check-filesystem-access`. Separate plan.
- No `run_command` change. It still inherits the environment it is given, has no `cwd`, and has no `timeout` — recorded in the spec's residuals.
- No curation of *which* variables a worker inherits. The port makes the set injectable and assertable; choosing a narrower set is a policy decision nobody has asked for.
