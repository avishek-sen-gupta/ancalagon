# Sandbox Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every worker inside a sandbox that confines writes to `write_root` and network to an allowlist, chosen by config and injected as a strategy.

**Architecture:** A `Sandbox` protocol with two methods — `wrap` for the command line, `environment` for the child's env. `Unsandboxed` is the null object; `Fence` writes a `fence.json` into the run directory and prepends `fence -s … --`. `cli.py` resolves the config's strategy name into an object and injects it into `SubprocessSpawner`, which is already the only module that constructs a process.

**Tech Stack:** Python 3.13, Pydantic, pytest, and the `fence` binary from Homebrew (`fencesandbox/fence`).

**Spec:** `docs/superpowers/specs/2026-08-16-sandbox-mode-design.md`

## Global Constraints

- Every protocol implementation **inherits** the protocol, per CLAUDE.md. `Unsandboxed(Sandbox)`, `Fence(Sandbox)`.
- Frozen Pydantic models for anything holding values. No dataclasses.
- `collections.abc.Sequence` and `Mapping` for parameters that are not mutated. Never `list` or `dict`.
- No comments except a one-line module header.
- Pyright strict must pass with zero errors; no `Any`, no `object`.
- Verify with `uv run python -m black . && uv run pyright && uv run python -m pytest tests/`.
- `fence` is on PATH at `/opt/homebrew/bin/fence`, version 0.1.66. Tests must not require it — they inject a fake.

---

### Task 1: The `Sandbox` protocol and `Unsandboxed`

**Files:**
- Create: `ancalagon/sandbox/__init__.py` (empty)
- Create: `ancalagon/sandbox/sandbox.py`
- Create: `ancalagon/sandbox/unsandboxed.py`
- Test: `tests/unit/test_sandbox.py`

**Interfaces:**
- Produces: `Sandbox` protocol with `wrap(command: Sequence[str]) -> Sequence[str]` and `environment() -> Mapping[str, str]`; `Unsandboxed` implementing both.

- [ ] **Step 1: Write the failing test**

```python
import pathlib

from ancalagon.sandbox.unsandboxed import Unsandboxed


def test_the_unsandboxed_strategy_changes_neither_the_command_nor_the_environment():
    command = ["python", "-m", "ancalagon.worker", "--agent-id", "3"]

    assert list(Unsandboxed().wrap(command)) == command
    assert dict(Unsandboxed().environment()) == {}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'ancalagon.sandbox'`

- [ ] **Step 3: Write the protocol**

```python
# ancalagon/sandbox/sandbox.py
# How a worker's command is wrapped before it is spawned, and what environment it gets.
import collections.abc
import typing


class Sandbox(typing.Protocol):
    def wrap(
        self, command: collections.abc.Sequence[str]
    ) -> collections.abc.Sequence[str]: ...

    def environment(self) -> collections.abc.Mapping[str, str]: ...
```

- [ ] **Step 4: Write the null object**

```python
# ancalagon/sandbox/unsandboxed.py
# The strategy that sandboxes nothing, so an unsandboxed run is a choice rather than a branch.
import collections.abc

from ancalagon.sandbox.sandbox import Sandbox


class Unsandboxed(Sandbox):
    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        return command

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {}
```

- [ ] **Step 5: Run the test and the gates**

Run: `uv run python -m black . -q && uv run pyright && uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: PASS, Pyright zero errors.

- [ ] **Step 6: Commit**

```bash
git add ancalagon/sandbox tests/unit/test_sandbox.py
git commit -m "Add a Sandbox strategy, and the one that sandboxes nothing"
```

---

### Task 2: The `Fence` strategy

**Files:**
- Create: `ancalagon/sandbox/fence.py`
- Modify: `tests/unit/test_sandbox.py`

**Interfaces:**
- Consumes: `Sandbox` from Task 1.
- Produces: `Fence(write_root: pathlib.Path, allowed_domains: Sequence[str], run_dir: pathlib.Path)`. Writes `<run_dir>/fence.json` when constructed.

- [ ] **Step 1: Write the failing test**

```python
import json

from ancalagon.sandbox.fence import Fence


def test_fence_writes_its_policy_and_wraps_the_command(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"

    sandbox = Fence(
        write_root=write_root,
        allowed_domains=["bedrock-runtime.us-east-1.amazonaws.com"],
        run_dir=run_dir,
    )

    policy = json.loads((run_dir / "fence.json").read_text())
    assert policy == {
        "network": {"allowedDomains": ["bedrock-runtime.us-east-1.amazonaws.com"]},
        "filesystem": {"allowWrite": [str(write_root)]},
    }

    assert list(sandbox.wrap(["python", "-m", "ancalagon.worker"])) == [
        "fence",
        "-s",
        str(run_dir / "fence.json"),
        "--",
        "python",
        "-m",
        "ancalagon.worker",
    ]
    assert dict(sandbox.environment()) == {"no_proxy": "", "NO_PROXY": ""}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'ancalagon.sandbox.fence'`

- [ ] **Step 3: Write it**

The policy is built from Pydantic models, not a hand-built dict, per the boundary rules in
CLAUDE.md. Put them in the same module — they exist only to be serialised here.

```python
# ancalagon/sandbox/fence.py
# Runs a worker under fence, which confines its writes and filters its network.
import collections.abc
import pathlib

import pydantic

from ancalagon.sandbox.sandbox import Sandbox

POLICY = "fence.json"


class Network(pydantic.BaseModel, frozen=True):
    allowedDomains: list[str]


class Filesystem(pydantic.BaseModel, frozen=True):
    allowWrite: list[str]


class Policy(pydantic.BaseModel, frozen=True):
    network: Network
    filesystem: Filesystem


class Fence(Sandbox):
    def __init__(
        self,
        write_root: pathlib.Path,
        allowed_domains: collections.abc.Sequence[str],
        run_dir: pathlib.Path,
    ):
        self.policy = run_dir / POLICY
        self.policy.write_text(
            Policy(
                network=Network(allowedDomains=list(allowed_domains)),
                filesystem=Filesystem(allowWrite=[str(write_root)]),
            ).model_dump_json()
        )

    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        return ["fence", "-s", str(self.policy), "--", *command]

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {"no_proxy": "", "NO_PROXY": ""}
```

- [ ] **Step 4: Run the test and the gates**

Run: `uv run python -m black . -q && uv run pyright && uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: PASS. Note `allowedDomains` and `allowWrite` are fence's spelling, not ours — they
are wire field names and must stay camelCase.

- [ ] **Step 5: Commit**

```bash
git add ancalagon/sandbox/fence.py tests/unit/test_sandbox.py
git commit -m "Add the fence sandbox strategy"
```

---

### Task 3: The spawner takes a `Sandbox`

**Files:**
- Modify: `ancalagon/supervisor/subprocess_spawner.py`
- Modify: `ancalagon/cli.py:112-118` (the `Supervisor` construction)
- Test: `tests/unit/test_sandbox.py`

**Interfaces:**
- Consumes: `Sandbox`, `Unsandboxed` from Task 1.
- Produces: `SubprocessSpawner(run_dir, config_path, sandbox: Sandbox = Unsandboxed())`.

- [ ] **Step 1: Write the failing test**

A fake `Sandbox` proves the spawner asks the strategy rather than hardcoding a prefix. It
records what it was given so the test can assert the worker command reached it intact.

```python
class RecordingSandbox(Sandbox):
    def __init__(self) -> None:
        self.seen: list[str] = []

    def wrap(self, command: collections.abc.Sequence[str]) -> collections.abc.Sequence[str]:
        self.seen = list(command)
        return ["prefix", *command]

    def environment(self) -> collections.abc.Mapping[str, str]:
        return {"MARKER": "set"}


def test_the_spawner_wraps_the_worker_command_with_its_sandbox(tmp_path: pathlib.Path):
    sandbox = RecordingSandbox()
    spawner = SubprocessSpawner(
        run_dir=tmp_path, config_path=tmp_path / "c.toml", sandbox=sandbox
    )

    process = spawner.spawn(tmp_path / "tasks" / "root", agent_id=7)
    process.kill()

    assert sandbox.seen[1:3] == ["-m", "ancalagon.worker"]
    assert "--agent-id" in sandbox.seen
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_sandbox.py -q`
Expected: FAIL, `SubprocessSpawner.__init__() got an unexpected keyword argument 'sandbox'`

- [ ] **Step 3: Change the spawner**

`spawn` builds the same list it builds today, then hands it to the sandbox. The environment
is the parent's, updated with whatever the strategy adds — `Unsandboxed` adds nothing, so
the default behaviour is byte-identical to today.

```python
    def __init__(
        self,
        run_dir: pathlib.Path,
        config_path: pathlib.Path,
        sandbox: Sandbox = Unsandboxed(),
    ):
        self.run_dir = run_dir
        self.config_path = config_path
        self.sandbox = sandbox

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        stderr.parent.mkdir(parents=True, exist_ok=True)
        command = [
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
        ]
        return subprocess.Popen(
            list(self.sandbox.wrap(command)),
            stdout=subprocess.DEVNULL,
            stderr=stderr.open("w"),
            cwd=self.run_dir,
            env={**os.environ, **self.sandbox.environment()},
        )
```

Add `import os` at the top.

- [ ] **Step 4: Run the test and the whole suite**

Run: `uv run python -m black . -q && uv run pyright && uv run python -m pytest tests/ -q`
Expected: PASS, 55 tests. The integration tests still pass because the default is
`Unsandboxed`.

- [ ] **Step 5: Commit**

```bash
git add ancalagon/supervisor/subprocess_spawner.py tests/unit/test_sandbox.py
git commit -m "Let the spawner ask a strategy how to wrap its worker"
```

---

### Task 4: Config carries the strategy and the domains

**Files:**
- Modify: `ancalagon/config/config.py`
- Modify: `ancalagon/config/load.py:31-50`
- Create: `ancalagon/sandbox/strategy.py`
- Modify: `ancalagon.example.toml`
- Modify: `ancalagon/cli.py`
- Test: `tests/unit/test_config_load.py`

**Interfaces:**
- Consumes: `Fence`, `Unsandboxed` from Tasks 1–2.
- Produces: `Config.allowed_domains: tuple[str, ...]`, `Config.sandbox: Strategy`, and
  `sandbox_of(strategy, config, run_dir) -> Sandbox`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config_load.py`. The existing `_config_file` helper writes the other
sections, so only the two new keys are given here.

```python
def test_the_sandbox_strategy_and_its_domains_come_from_the_config(tmp_path: pathlib.Path):
    path = _config_file(
        tmp_path,
        "sandboxed.toml",
        '[run]\nrun_dir = ""\ngoal_file = ""\ncontract_module = ""\ncontract_class = ""\n',
    )
    config = load_config(path)

    assert config.sandbox is Strategy.FENCE
    assert config.allowed_domains == ("bedrock-runtime.us-east-1.amazonaws.com",)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_config_load.py -q`
Expected: FAIL, `NameError: name 'Strategy' is not defined`

- [ ] **Step 3: Add the enum**

An enum rather than a string, per the design principles: fixed sets are enums, and the enum
is resolved into an object early.

```python
# ancalagon/sandbox/strategy.py
# The sandboxes a run may choose between, named in the config.
import enum


class Strategy(enum.StrEnum):
    NONE = "none"
    FENCE = "fence"
```

- [ ] **Step 4: Add the config fields**

In `ancalagon/config/config.py`, on `Config`:

```python
    allowed_domains: tuple[str, ...] = ()
    sandbox: Strategy = Strategy.FENCE
```

In `ancalagon/config/load.py`, inside `load_config`'s `Config(...)` call:

```python
        allowed_domains=tuple(model["allowed_domains"]),
        sandbox=Strategy(raw["sandbox"]["strategy"]),
```

Read by bracket, never `.get()` — the existing comment in that file explains why: a config
file must be complete, and `Config`'s defaults exist for callers building one in code.

- [ ] **Step 5: Add the keys to the example config**

In `ancalagon.example.toml`, under `[model]`:

```toml
allowed_domains = ["bedrock-runtime.us-east-1.amazonaws.com"]
```

and a new section:

```toml
[sandbox]
strategy = "fence"   # or "none"
```

- [ ] **Step 6: Resolve the enum in the CLI**

Add to `ancalagon/cli.py`, and call it where the `Supervisor` is built:

```python
def sandbox_of(config: Config, run_dir: pathlib.Path) -> Sandbox:
    if config.sandbox is Strategy.NONE:
        return Unsandboxed()
    return Fence(
        write_root=config.write_root,
        allowed_domains=config.allowed_domains,
        run_dir=run_dir,
    )
```

```python
        spawner=SubprocessSpawner(
            run_dir=run_dir,
            config_path=config_path.resolve(),
            sandbox=sandbox_of(config, run_dir),
        ),
```

- [ ] **Step 7: Run the whole suite**

Run: `uv run python -m black . -q && uv run pyright && uv run python -m pytest tests/ -q`
Expected: several config tests fail with `KeyError: 'sandbox'`, because every inline TOML in
the tests is now incomplete. Fix each by adding the two keys, the same way the
`contract_module`/`contract_class` split was handled in commit `2059ff6`.

- [ ] **Step 8: Commit**

```bash
git add ancalagon tests ancalagon.example.toml
git commit -m "Choose a sandbox in the config, and resolve it in the CLI"
```

---

### Task 5: Prove it against the real fence binary

**Files:**
- Create: `tests/integration/test_sandbox.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the test**

Gated on the binary being present, in the style of the other gated integration tests. It
asserts the two guarantees the spec claims, against the real binary rather than a fake.

```python
import os
import pathlib
import shutil
import subprocess

import pytest

from ancalagon.sandbox.fence import Fence

pytestmark = pytest.mark.skipif(
    shutil.which("fence") is None, reason="fence is not installed"
)


def test_fence_confines_writes_and_leaves_the_toolchain_working(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_root = tmp_path / "ws"
    write_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    sandbox = Fence(write_root=write_root, allowed_domains=[], run_dir=run_dir)
    env = {**os.environ, **sandbox.environment()}

    allowed = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo ok > {write_root / 'a.txt'}"])),
        capture_output=True,
        env=env,
    )
    assert allowed.returncode == 0
    assert (write_root / "a.txt").read_text() == "ok\n"

    refused = subprocess.run(
        list(sandbox.wrap(["sh", "-c", f"echo no > {outside / 'b.txt'}"])),
        capture_output=True,
        env=env,
    )
    assert refused.returncode != 0
    assert not (outside / "b.txt").exists()

    toolchain = subprocess.run(
        list(sandbox.wrap(["rg", "--version"])), capture_output=True, text=True, env=env
    )
    assert toolchain.returncode == 0
    assert toolchain.stdout.startswith("ripgrep")
```

- [ ] **Step 2: Run it**

Run: `uv run python -m pytest tests/integration/test_sandbox.py -q`
Expected: PASS on a machine with fence; SKIPPED otherwise.

- [ ] **Step 3: Mutation-check it**

Break `Fence.wrap` to return `command` unchanged and run again. The write-refused assertion
must fail. Restore it. A test that passes with the sandbox removed is not testing the
sandbox.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_sandbox.py
git commit -m "Prove the sandbox refuses a write outside the write root"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: README**

Under "Running", after the config snippet, state that runs are sandboxed by default, that
`fence` must be installed, and that `[sandbox] strategy = "none"` turns it off. State plainly
that writes are confined and reads are not.

- [ ] **Step 2: architecture.md**

In section 2, where `subprocess_spawner.py` is described as the only module that constructs a
process, add that it wraps its command with an injected `Sandbox`, and that `Fence` writes its
policy into the run directory so a run records what it ran under. Note that reads are
unrestricted and why, referencing the spec rather than repeating the experiment.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/architecture.md
git commit -m "Document sandbox mode"
```

---

## Self-review against the spec

**Coverage.** `Sandbox` protocol and `Unsandboxed` → Task 1. `Fence`, its policy file, the
`no_proxy` clearing → Task 2. Spawner injection → Task 3. `allowed_domains`, `[sandbox]
strategy`, enum resolution in the CLI → Task 4. The write-confinement and toolchain claims →
Task 5. The "reads are unrestricted" statement → Task 6.

Not covered, deliberately: the spec's Linux caveat. Nothing here tests Linux, and Task 5 is
skipped where `fence` is absent, so the Linux path stays unverified exactly as the spec says.

**Placeholders.** None. Every step has its code or its exact command.

**Consistency.** `Sandbox`, `Unsandboxed`, `Fence`, `Strategy`, `sandbox_of` are spelled the
same in every task. `wrap` takes and returns `Sequence[str]`; `environment` returns
`Mapping[str, str]`; `Fence.__init__` takes `write_root`, `allowed_domains`, `run_dir` in that
order everywhere.
