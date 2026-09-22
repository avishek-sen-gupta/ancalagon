# Several Write Roots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `write_root` into `home` (where runs live) and `write_roots` (where agents may write), so agents can write under several directories.

**Architecture:** `Config` replaces `write_root` with `home` and `write_roots`. `Workspace` takes a tuple of write roots; `from_config` adds `home` to both write and read roots, so everything reachable today stays reachable. The fence, the system prompt, `cli`, `watch` and `check_contracts` switch to the new fields. Loading a config that still names `write_root` is refused.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, uv, TOML.

**Spec:** `docs/superpowers/specs/2026-09-22-several-write-roots-design.md`

## Global Constraints

- Pyright strict, zero errors. No `Any`, no `object`, no bare generics.
- No comments in Python except a one-line header per module or class. TOML config files may carry comments; the shipped configs must.
- Frozen models. No `None` defaults. No mocks.
- Few tests, each covering a whole behaviour; extend existing behaviour tests.
- Never modify `docs/superpowers/specs/` or `docs/superpowers/plans/`.
- No names from codebases under analysis in anything tracked.
- Refusal message for the old key, verbatim: `[workspace] write_root was split into home (where runs live) and write_roots (where agents may write)`
- Verify: `uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports`. Run the whole integration suite.

---

### Task 1: Split write_root into home and write_roots

One commit. `Config` cannot be half renamed and still type-check.

**Files:**
- Modify: `ancalagon/config/config.py`, `ancalagon/config/load.py`
- Modify: `ancalagon/workspace/workspace.py`
- Modify: `ancalagon/sandbox/fence.py`, `ancalagon/run.py` (`sandbox_of`)
- Modify: `ancalagon/session.py` (`_scopes`)
- Modify: `ancalagon/cli.py`, `ancalagon/watch_command.py`, `ancalagon/watching/watch.py`, `ancalagon/check_contracts.py`
- Modify: tool descriptions and headers in `ancalagon/tools/files/write_file.py`, `edit_file.py`, `delete_file.py`, `append_file.py`, `ancalagon/tools/artifacts/edit_json.py`
- Modify: `ancalagon.toml`, `ancalagon.example.toml`, `research.toml`, `blackboard.toml`
- Modify: `README.md`, `docs/architecture.md`
- Test: `tests/unit/test_workspace_scoping.py`, `tests/unit/test_sandbox.py`, `tests/unit/test_watching.py`, and every other test or example referring to `write_root` (about 215 references in 33 files under `tests/` and `examples/`)

**Interfaces:**
- Produces: `Config.home: pathlib.PurePath` (required), `Config.write_roots: tuple[pathlib.PurePath, ...] = ()`. `Config.write_root` no longer exists.
- Produces: `Workspace(fs: FileSystem, write_roots: tuple[pathlib.PurePath, ...], read_roots: tuple[pathlib.PurePath, ...])`, attribute `write_roots`. `Workspace.write_root` no longer exists.
- Produces: `Fence(write_roots: collections.abc.Sequence[pathlib.PurePath], allowed_domains, run_dir, fs, log_socket)`.
- Produces: `Watch.home` replaces `Watch.write_root`; `concern(home, fs)`.

- [ ] **Step 1: Write the failing workspace and config test**

In `tests/unit/test_workspace_scoping.py`, rewrite `test_scoping_rejects_every_escape_and_config_round_trips` so it covers two write roots, the home, and the old key. Keep every existing escape assertion. The new shape:

```python
def test_scoping_rejects_every_escape_and_config_round_trips(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    second_root = tmp_path / "notes"
    read_only = tmp_path / "artifacts"
    outside = tmp_path / "elsewhere"
    for d in (write_root, second_root, read_only, outside):
        d.mkdir()
    (read_only / "a.txt").write_text("data")
    (outside / "secret.txt").write_text("nope")

    ws = Workspace(
        RealFileSystem(),
        write_roots=(write_root, second_root),
        read_roots=(read_only, write_root),
    )

    assert ws.resolve_write(write_root / "out.json") == (write_root / "out.json").resolve()
    assert ws.resolve_write(second_root / "n.md") == (second_root / "n.md").resolve()
    assert ws.resolve_read(read_only / "a.txt") == (read_only / "a.txt").resolve()
    assert ws.resolve_read(write_root / "out.json") == (write_root / "out.json").resolve()

    with pytest.raises(ScopeError) as refused:
        ws.resolve_write(read_only / "a.txt")
    assert str(refused.value) == (
        f"{read_only / 'a.txt'} is outside write_roots "
        f"{(write_root.resolve(), second_root.resolve())}"
    )
```

…followed by the existing `resolve_read(outside …)`, `..`, symlink and `ToolContext` assertions unchanged, and then the config section. The TOML's `[workspace]` becomes:

```toml
[workspace]
home = "{write_root}"
write_roots = ["{second_root}"]
read_roots = ["{read_only}"]
```

and its assertions:

```python
    config = load_config(config_path, RealFileSystem())
    assert config.home == write_root
    assert config.write_roots == (second_root,)
    assert config.read_roots == (read_only,)
    ...the existing model/limits assertions unchanged...
    from_config = Workspace.from_config(config, RealFileSystem())
    assert from_config.write_roots == (second_root.resolve(), write_root.resolve())
    assert from_config.read_roots == (
        read_only.resolve(),
        second_root.resolve(),
        write_root.resolve(),
    )

    config_path.write_text(config_path.read_text().replace(
        f'home = "{write_root}"\nwrite_roots = ["{second_root}"]',
        f'write_root = "{write_root}"',
    ))
    with pytest.raises(ValueError) as old_key:
        load_config(config_path, RealFileSystem())
    assert str(old_key.value) == (
        "[workspace] write_root was split into home (where runs live) and "
        "write_roots (where agents may write)"
    )
```

`tmp_path` may sit under a symlink on macOS (`/var` → `/private/var`); if the `str(refused.value)` or `from_config` assertions differ only by that, compare against `.resolve()` of each path as shown rather than the raw path.

- [ ] **Step 2: Write the failing fence test**

In `tests/unit/test_sandbox.py`, `test_fence_writes_its_policy_and_wraps_the_command`:

```python
    write_root = tmp_path / "ws"
    second_root = tmp_path / "notes"

    sandbox = Fence(
        write_roots=[write_root, second_root],
        allowed_domains=["bedrock-runtime.us-east-1.amazonaws.com", "*.example.com"],
        run_dir=run_dir,
        fs=RealFileSystem(),
        log_socket="",
    )
```

and the policy's filesystem entry:

```python
        "filesystem": {"allowWrite": [str(write_root), str(second_root), str(run_dir)]},
```

Update every other `Fence(write_root=X, …)` in `tests/unit/test_sandbox.py` and `tests/integration/test_sandbox.py` to `Fence(write_roots=[X], …)` and their expected `allowWrite` to match.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_workspace_scoping.py tests/unit/test_sandbox.py -v`
Expected: FAIL — `Workspace` and `Fence` have no `write_roots` parameter.

- [ ] **Step 4: Split the config**

`ancalagon/config/config.py`: replace `write_root: pathlib.PurePath` with

```python
    home: pathlib.PurePath
    write_roots: tuple[pathlib.PurePath, ...] = ()
```

placing `home` first and `write_roots` directly after `read_roots`. The header's "three that cannot be guessed" remains true (`home`, `read_roots`, `model`).

`ancalagon/config/load.py`: add a module constant and a refusal in `load_config`, before building `Config`:

```python
SPLIT_WRITE_ROOT = (
    "[workspace] write_root was split into home (where runs live) and "
    "write_roots (where agents may write)"
)
```

```python
    if "write_root" in workspace:
        raise ValueError(SPLIT_WRITE_ROOT)
```

and in the `Config(...)` call replace the `write_root=` line with:

```python
        home=_root(base, workspace["home"], fs),
        write_roots=tuple(_root(base, p, fs) for p in workspace["write_roots"]),
```

- [ ] **Step 5: Give the workspace several write roots**

`ancalagon/workspace/workspace.py`:

```python
    def __init__(
        self,
        fs: FileSystem,
        write_roots: tuple[pathlib.PurePath, ...],
        read_roots: tuple[pathlib.PurePath, ...],
    ):
        self.fs = fs
        self.write_roots = tuple(fs.resolve(fs.expanduser(r)) for r in write_roots)
        self.read_roots = tuple(fs.resolve(fs.expanduser(r)) for r in read_roots)

    @classmethod
    def from_config(cls, config: "Config", fs: FileSystem) -> "Workspace":
        return cls(
            fs,
            write_roots=(*config.write_roots, config.home),
            read_roots=(*config.read_roots, *config.write_roots, config.home),
        )

    def resolve_write(self, path: pathlib.PurePath) -> pathlib.PurePath:
        resolved = self.fs.resolve(self.fs.expanduser(path))
        if not any(resolved.is_relative_to(root) for root in self.write_roots):
            raise ScopeError(f"{path} is outside write_roots {self.write_roots}{_hint(path)}")
        return resolved
```

- [ ] **Step 6: Fence, prompt, harness home, tool descriptions**

`ancalagon/sandbox/fence.py`: the parameter becomes `write_roots: collections.abc.Sequence[pathlib.PurePath]` and the policy line:

```python
                filesystem=Filesystem(
                    allowWrite=[*(str(root) for root in write_roots), str(run_dir)]
                ),
```

`ancalagon/run.py` `sandbox_of`: `write_roots=(*config.write_roots, config.home),`.

`ancalagon/session.py` `_scopes`:

```python
        writable = ", ".join(str(r) for r in self.ctx.workspace.write_roots)
```

and `f"You may write under: {writable}\n"`.

`ancalagon/cli.py`: rename the `write_root` parameters of `_allocated_run_dir` and `created_run_dir` to `home`, and `init_command` passes `config.home`.

`ancalagon/watching/watch.py`: rename the `write_root` parameter and attribute to `home`.

`ancalagon/watch_command.py`: rename `write_root` to `home` throughout; `_root` returns `load_config(...).home`; `concern` returns `f"nothing to watch under {home}; is this the home?"`; `watch_command` uses `watch.home`.

`ancalagon/check_contracts.py` `_hook_fault`: `config.home` where it passed `config.write_root`.

Tool descriptions and headers: in `write_file.py`, `edit_file.py`, `delete_file.py`, `append_file.py`, replace "the workspace write root" with "a write root" in both the module header and `description`; in `edit_json.py`, "inside the write root" becomes "inside a write root".

- [ ] **Step 7: Run the focused tests**

Run: `uv run pytest tests/unit/test_workspace_scoping.py tests/unit/test_sandbox.py -v`
Expected: PASS.

- [ ] **Step 8: Rename every remaining reference in tests and examples**

Find them:

```bash
rg -n 'write_root' tests examples
ast-grep --lang python -p 'Config($$$, write_root=$X, $$$)' tests examples
ast-grep --lang python -p 'Workspace($$$, write_root=$X, $$$)' tests examples
```

Rules, applied mechanically:
- `Config(write_root=X, …)` → `Config(home=X, …)`. The home is an implicit write root, so behaviour is unchanged.
- `Workspace(fs, write_root=X, read_roots=…)` → `Workspace(fs, write_roots=(X,), read_roots=…)`.
- `ctx.workspace.write_root` / `ws.write_root` → `….write_roots[0]`.
- `config.write_root` → `config.home`.
- `watch.write_root` → `watch.home`; the two `concern` assertions in `tests/unit/test_watching.py:236-237` end in `is this the home?`.
- Any test TOML with `write_root = "X"` → `home = "X"` followed by `write_roots = []` on the next line. This includes the TOML strings in `tests/integration/*.py`.
- Local variables that happen to be called `write_root` in tests may keep their names; only the API changes.

Then:

```bash
rg -n 'write_root\b' ancalagon tests examples
```

Expected: matches only for local variable names in tests, none for `.write_root` attribute access, `write_root=` keywords, or TOML keys.

- [ ] **Step 9: Migrate the shipped configs**

`ancalagon.example.toml`, replace the `[workspace]` body with:

```toml
[workspace]
# home and write_roots replace the old write_root, which did both jobs and is now refused.
# Where runs live: run directories are allocated under <home>/runs, and watch reads it. Agents
# may always read and write under home, because tool output is written beside each task.
home = "./ws"
# Further directories agents may write under, beyond home. May be empty.
write_roots = []
# Every directory agents may read. home and write_roots are always readable and need not be
# listed.
read_roots = [".", "./ancalagon", "./docs", "./tests", "./scripts"]
```

and in `[sandbox]`, "confines each worker to write_root and the allowed domains above" becomes "confines each worker to home, write_roots and the allowed domains above".

`ancalagon.toml`, `research.toml`, `blackboard.toml`: `write_root = "X"` becomes

```toml
# home and write_roots replace write_root: home holds runs/, write_roots lists further
# directories agents may write under.
home = "X"
write_roots = []
```

keeping each file's own `X`.

Run: `uv run pytest tests/unit/test_config_load.py -v`
Expected: PASS, including `test_the_example_config_this_repo_ships_satisfies_its_own_contracts` and `test_the_research_config_this_repo_ships_types_every_answer_file`.

- [ ] **Step 10: Update the living docs**

```bash
rg -n 'write_root|write root' README.md docs/architecture.md
```

Rewrite each hit to name `home` where it means where runs live or what `watch` reads, and `write_roots` (or "a write root") where it means where agents may write. Configuration examples in the README use the new `[workspace]` keys.

In `docs/architecture.md`, directly after the numbered item beginning "Reaches the file through `workspace/workspace.py`", add a paragraph:

```
**Known limitation: the home is writable by agents.** `Workspace.from_config` makes `home` an
implicit write root, because tool output is written under `<home>/runs/.../tools/` and agents
read it back through the `[full output: …]` pointer. The same rule lets an agent write
anywhere under the home, including `bus.db` and other tasks' transcripts. This needs hardening:
the home should become readable by agents and written only by the harness, with
`ToolContext.write_output` writing the task's own output directory outside the agents' write
scope.
```

- [ ] **Step 11: Self-review and verify**

```bash
rg -n 'write_root' ancalagon README.md docs/architecture.md ancalagon.toml ancalagon.example.toml research.toml blackboard.toml
```

Expected: only the refusal message constant and its check in `load.py`, the TOML comments naming the old key, and the architecture/README text describing the split.

```bash
uv run python -m black . && uv run pyright && uv run pytest tests/unit && uv run pytest tests/integration && uv run lint-imports
```

Expected: all pass.

Mutation-check: make `resolve_write` check only `self.write_roots[0]` and confirm the workspace test fails on the second root; restore. Delete the `write_root` refusal and confirm the test fails; restore.

- [ ] **Step 12: Commit**

```bash
git add ancalagon tests examples README.md docs/architecture.md ancalagon.toml ancalagon.example.toml research.toml blackboard.toml
git commit -m "Split write_root into home and several write roots

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```
