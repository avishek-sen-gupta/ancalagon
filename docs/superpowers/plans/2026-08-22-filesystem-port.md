# FileSystem Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put file access behind a port, and make `Workspace` the only way a tool reaches the disk, so path scoping stops being a convention each tool re-enacts and becomes the only way through.

**Architecture:** A `FileSystem` protocol in a new leaf package `ancalagon/fs/`, with `RealFileSystem` as its only adapter. `Workspace` holds one and gains scoped operations that resolve before they delegate. Harness-internal code — which works on paths the harness builds, not paths a model supplies — takes the port directly. A precommit ripgrep script bans the raw `pathlib` methods outside the adapter.

**Tech Stack:** Python 3.13, `typing.Protocol`, pytest with `tmp_path`, import-linter, a bash + ripgrep precommit script.

**Spec:** `docs/superpowers/specs/2026-08-22-ports-for-filesystem-and-environment-design.md` — this plan implements the `FileSystem` half. The `Environment` half shipped as `e020ac6`; follow its shape.

## Global Constraints

- Pyright strict, **zero errors**. `Any` and `object` are banned; every generic is parameterised.
- **No comments** except a one-line header on a class or module.
- **No fake filesystem.** `RealFileSystem` is the only adapter. Tests keep using `pytest`'s `tmp_path` with it, per `docs/guidelines/testing-patterns.md`. Do not write a `FakeFileSystem` — the `Environment` port has a fake because it is one method; this one is eleven, and an in-memory reimplementation of `mkdir(parents=)`, `glob` and `iterdir` semantics is a liability, not a test aid.
- **Text is UTF-8, always.** The port takes no `encoding` parameter. Call sites are inconsistent today (`worker.py` uses the platform default, the file tools pass `encoding="utf-8"`); they unify on UTF-8.
- Every package under `ancalagon/` has an `__init__.py`. `ancalagon/fs/` needs one, or import-linter reports `module ancalagon.fs does not exist`.
- A class implementing a `Protocol` **inherits** it. Pyright reports a missing member at the **instantiation** site, as `Cannot instantiate abstract class`, not at the class definition — so verification must run `uv run pyright` over the whole project, never a single file or directory.
- No `None` defaults, no `None` returns, no defensive guards, no bare `except`. No mocking.
- Few tests, each covering a whole behaviour. Prefer extending an existing behaviour test to adding a file.
- Never name an external codebase under analysis in any tracked artifact.
- **There is no bypass for the pre-commit hooks.** Never `git stash`.
- Verify with: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`.
- Counts at the start: **85 unit**, **10 integration passed / 2 skipped**, **contracts 4 kept**. Tasks 2–4 are refactors and must not change any count. Only Tasks 1 and 5 add tests.
- **Talisman will flag new files.** Append an entry per newly flagged file; for a file already listed whose content changed, replace its checksum **in place** — only the first entry per filename is honoured. Use the checksum Talisman reports.

## The census this plan works from

44 call sites across 22 files, counted with:

```bash
grep -rn --include='*.py' -o '\.\(read_text\|write_text\|read_bytes\|mkdir\|unlink\|iterdir\|glob\|exists\|is_file\|is_dir\)(' ancalagon
```

| Group | Files | Sites | Task |
|---|---|---|---|
| Tool-facing, scoped through `Workspace` | `tools/files/{read,write,edit,delete}_file.py`, `tools/files/list_dir.py`, `tools/history/git_history.py`, `tools/parse/tree_sitter_tool.py`, `tools/registry/tool_context.py` | 14 | 2 |
| Harness leaves | `transcript/{transcript,history}.py`, `config/load.py`, `migrations.py`, `sandbox/fence.py`, `bus/connect.py`, `migrate_command.py` | 9 | 3 |
| Harness entry points and delegates | `worker.py`, `cli.py`, `answer.py`, `supervisor/supervisor.py`, `supervisor/subprocess_spawner.py`, `tools/delegate/{collect_task,delegate_to}.py` | 21 | 4 |

`.resolve()` and `.expanduser()` are **not** in scope — see the spec's residuals. Of the nine `.open(` calls in the package, seven are `LifecycleStore.open` and only two are file handles (`transcript/transcript.py`, `supervisor/subprocess_spawner.py`).

---

### Task 1: The port and its adapter

**Files:**
- Create: `ancalagon/fs/__init__.py` (empty), `ancalagon/fs/file_system.py`, `ancalagon/fs/real_file_system.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_file_system.py`

**Interfaces:**
- Produces: `FileSystem` protocol and `RealFileSystem()`. Every later task consumes these.

Signatures, fixed here and used verbatim downstream:

```python
def read_text(self, path: pathlib.Path) -> str: ...
def write_text(self, path: pathlib.Path, text: str) -> None: ...
def read_bytes(self, path: pathlib.Path) -> bytes: ...
def mkdir(self, path: pathlib.Path, parents: bool = False, exist_ok: bool = False) -> None: ...
def unlink(self, path: pathlib.Path) -> None: ...
def iterdir(self, path: pathlib.Path) -> tuple[pathlib.Path, ...]: ...
def glob(self, path: pathlib.Path, pattern: str) -> tuple[pathlib.Path, ...]: ...
def exists(self, path: pathlib.Path) -> bool: ...
def is_file(self, path: pathlib.Path) -> bool: ...
def is_dir(self, path: pathlib.Path) -> bool: ...
def open_append(self, path: pathlib.Path) -> typing.TextIO: ...
def open_write(self, path: pathlib.Path) -> typing.TextIO: ...
```

`iterdir` and `glob` return tuples, not iterators: the callers all consume them once and the codebase prefers immutable values. `read_text`/`write_text`/`open_*` are UTF-8 with no parameter.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_file_system.py`. One test, covering the whole port against a real directory:

```python
import pathlib

from ancalagon.fs.real_file_system import RealFileSystem


def test_the_real_file_system_reads_writes_lists_and_reports_what_is_there(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    nested = tmp_path / "a" / "b"

    fs.mkdir(nested, parents=True)
    assert fs.is_dir(nested) is True
    fs.mkdir(nested, parents=True, exist_ok=True)

    note = nested / "note.txt"
    assert fs.exists(note) is False
    fs.write_text(note, "hello é")
    assert fs.read_text(note) == "hello é"
    assert fs.read_bytes(note) == "hello é".encode("utf-8")
    assert (fs.exists(note), fs.is_file(note), fs.is_dir(note)) == (True, True, False)

    fs.write_text(nested / "other.md", "x")
    assert fs.iterdir(nested) == (nested / "note.txt", nested / "other.md")
    assert fs.glob(nested, "*.md") == (nested / "other.md",)

    with fs.open_append(note) as handle:
        handle.write("\nmore")
    assert fs.read_text(note) == "hello é\nmore"

    with fs.open_write(note) as handle:
        handle.write("replaced")
    assert fs.read_text(note) == "replaced"

    fs.unlink(note)
    assert fs.exists(note) is False
```

`iterdir` and `glob` must be **sorted** for those assertions to hold — `pathlib.Path.iterdir` yields in directory order, which is not alphabetical. Sort in the adapter.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m pytest tests/unit/test_file_system.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ancalagon.fs'`

- [ ] **Step 3: Write the protocol**

Create `ancalagon/fs/file_system.py` with a one-line module header, `class FileSystem(typing.Protocol):` and the twelve signatures above, each with a `...` body.

- [ ] **Step 4: Write the adapter**

Create `ancalagon/fs/real_file_system.py`:

```python
# The only place in the codebase that touches a file.
import pathlib
import typing

from ancalagon.fs.file_system import FileSystem


class RealFileSystem(FileSystem):
    def read_text(self, path: pathlib.Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: pathlib.Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def read_bytes(self, path: pathlib.Path) -> bytes:
        return path.read_bytes()

    def mkdir(self, path: pathlib.Path, parents: bool = False, exist_ok: bool = False) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def unlink(self, path: pathlib.Path) -> None:
        path.unlink()

    def iterdir(self, path: pathlib.Path) -> tuple[pathlib.Path, ...]:
        return tuple(sorted(path.iterdir()))

    def glob(self, path: pathlib.Path, pattern: str) -> tuple[pathlib.Path, ...]:
        return tuple(sorted(path.glob(pattern)))

    def exists(self, path: pathlib.Path) -> bool:
        return path.exists()

    def is_file(self, path: pathlib.Path) -> bool:
        return path.is_file()

    def is_dir(self, path: pathlib.Path) -> bool:
        return path.is_dir()

    def open_append(self, path: pathlib.Path) -> typing.TextIO:
        return path.open("a", encoding="utf-8")

    def open_write(self, path: pathlib.Path) -> typing.TextIO:
        return path.open("w", encoding="utf-8")
```

- [ ] **Step 5: Add the layer and the contract sources**

In `pyproject.toml`, `ancalagon.fs` is a leaf importing only `pathlib` and `typing`. Put it beside `ancalagon.env` on the bottom layer:

```toml
    "ancalagon.migrations",
    "ancalagon.env : ancalagon.fs",
]
```

Add `"ancalagon.fs"` to the `modules` list of `Sibling leaves are independent`, and to `source_modules` of `SQL stays in the adapters` in alphabetical position.

- [ ] **Step 6: Run the test and the contracts**

Run: `uv run python -m pytest tests/unit/test_file_system.py -q && uv run lint-imports`
Expected: 1 test passes; `4 kept, 0 broken`.

- [ ] **Step 7: Prove the layer fires**

Add `import ancalagon.clock.clock` to `ancalagon/fs/file_system.py`, run `uv run lint-imports`, and confirm **both** `Layers point downward` and `Sibling leaves are independent` report BROKEN naming `ancalagon.fs -> ancalagon.clock`. Remove it and confirm `4 kept`. Record both outputs in the task report.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run lint-imports
git add -A && git commit -m "A file system is a port with one adapter"
```

Expected: 86 unit tests. Talisman may flag the new files; follow the constraint above.

---

### Task 2: Workspace becomes the scoped way to the disk

**Files:**
- Modify: `ancalagon/workspace/workspace.py`
- Modify: `ancalagon/tools/files/{read_file,write_file,edit_file,delete_file,list_dir}.py`
- Modify: `ancalagon/tools/history/git_history.py`, `ancalagon/tools/parse/tree_sitter_tool.py`, `ancalagon/tools/registry/tool_context.py`
- Modify: `ancalagon/worker.py:148-149` (the sole `Workspace.from_config` call)
- Test: `tests/unit/test_workspace_scoping.py`, `tests/unit/test_tools.py` — extend, do not add files

**Interfaces:**
- Consumes: `FileSystem`, `RealFileSystem`.
- Produces: `Workspace(fs, write_root, read_roots)`, `Workspace.from_config(config, fs)`, and scoped methods mirroring the port's names, each taking an **unresolved** path.

`Workspace` keeps `resolve_read` and `resolve_write` public: `ripgrep`, `ast_grep`, `find_symbol` and `code_stats` need a resolved path as a string for a subprocess, not its contents. `Workspace.__init__` keeps calling `.expanduser().resolve()` on its roots — those are out of scope.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_workspace_scoping.py`, add a test that the scoped methods refuse an out-of-scope path *without* touching the disk, and read through when in scope:

```python
def test_workspace_reads_and_writes_only_inside_its_roots(tmp_path: pathlib.Path):
    write_root = tmp_path / "ws"
    write_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    workspace = Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,))

    workspace.write_text(write_root / "in.txt", "fine")
    assert workspace.read_text(write_root / "in.txt") == "fine"

    with pytest.raises(ScopeError):
        workspace.read_text(outside)
    with pytest.raises(ScopeError):
        workspace.write_text(outside, "clobbered")
    assert outside.read_text(encoding="utf-8") == "secret"
```

The last assertion is the point: a refused write must not have happened.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run python -m pytest tests/unit/test_workspace_scoping.py -q`
Expected: FAIL — `Workspace() takes 2 positional arguments` or `AttributeError: 'Workspace' object has no attribute 'read_text'`.

- [ ] **Step 3: Give Workspace the port**

`FileSystem` becomes the first constructor parameter, and `from_config` takes it too. Add one scoped method per operation the tools use — `read_text`, `write_text`, `read_bytes`, `mkdir`, `unlink`, `iterdir`, `exists`, `is_file`, `is_dir` — each resolving first. Reads resolve with `resolve_read`; `write_text`, `mkdir` and `unlink` resolve with `resolve_write`.

```python
    def read_text(self, path: pathlib.Path) -> str:
        return self.fs.read_text(self.resolve_read(path))

    def write_text(self, path: pathlib.Path, text: str) -> None:
        self.fs.write_text(self.resolve_write(path), text)
```

Do **not** add `glob` or the `open_*` handles: no tool uses them.

- [ ] **Step 4: Migrate the eight tool files**

Each tool currently resolves and then calls `pathlib` itself. Collapse both into the scoped call. `read_file.py` is the pattern:

```python
            path = ctx.workspace.resolve_read(args.path)
            if not path.is_file():
                ...
            lines = path.read_text(encoding="utf-8").splitlines()
```

becomes

```python
            if not ctx.workspace.is_file(args.path):
                ...
            lines = ctx.workspace.read_text(args.path).splitlines()
```

Keep each tool's existing error messages and behaviour exactly. Two need care:

- `git_history.py` calls `path.is_dir()` and then passes `path.parent` to a subprocess, so it still needs `resolve_read` for the argv value — use the scoped predicate but keep the resolved path for the command.
- `tool_context.py` writes into `output_dir`, which it builds itself; it resolves with `resolve_write` already. Route its `mkdir` and `write_text` through the scoped methods.

- [ ] **Step 5: Update the construction site**

`ancalagon/worker.py:149` — `Workspace.from_config(config)` becomes `Workspace.from_config(config, fs)`, where `fs` is a `RealFileSystem()` constructed in `worker.main`. Task 4 threads that same instance further; for now constructing it in `main` is enough.

- [ ] **Step 6: Run the suites**

Run: `uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q`
Expected: 87 unit (85 + Task 1's + this one), 10 integration passed / 2 skipped. **No other count moves.** A changed expectation elsewhere means behaviour drifted — stop and report it rather than editing the assertion.

- [ ] **Step 7: Mutation-check the scoping test**

Make `write_text` resolve with `resolve_read` instead of `resolve_write` and confirm the out-of-scope write assertion fails. Restore. Record the output.

- [ ] **Step 8: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q && uv run lint-imports
git add -A && git commit -m "Reaching a file goes through the workspace that scopes it"
```

---

### Task 3: The harness leaves

**Files:**
- Modify: `ancalagon/transcript/transcript.py`, `ancalagon/transcript/history.py`, `ancalagon/config/load.py`, `ancalagon/migrations.py`, `ancalagon/sandbox/fence.py`, `ancalagon/bus/connect.py`, `ancalagon/migrate_command.py`
- Modify: every construction and call site of those — `worker.py`, `answer.py`, `cli.py`, and the tests that call `load_config`, `migrate_file`, `migrate`, `connect` or build a `Transcript`
- Test: extend existing tests only

**Interfaces:**
- Consumes: `FileSystem`, `RealFileSystem`.
- Produces: `Transcript(fs, path, agent_id)`, `history.load(fs, path)`, `load_config(path, fs)`, `migrations.{latest_version,migrate,migrate_file}` taking `fs`, `Fence(..., fs)`, `connect(path, fs)`, `migrate_command(path, to, fs)`.

These are the modules with no dependants beyond the entry points, so they can move before `worker.py` and `cli.py` are restructured in Task 4.

`migrations.py` is the awkward one: `DIRECTORY` is a module-level `pathlib.Path` and `latest_version()`/`_script()` glob it. Both take `fs` as a parameter; `DIRECTORY` stays a module constant, since it is a path built from `__file__`, not an I/O call.

`transcript.py` holds an open handle from `path.open("a")`. It becomes `fs.open_append(path)`. The `mkdir` before it becomes `fs.mkdir(path.parent, parents=True, exist_ok=True)`.

- [ ] **Step 1: Thread the port through each leaf**

Take them one at a time, running `uv run pyright` after each to find the call sites — Pyright names every one, so there is no need to grep for them. Do not batch all seven before checking.

- [ ] **Step 2: Update the tests**

Tests that construct these directly need a `RealFileSystem()`. They keep using `tmp_path`; nothing becomes disk-free.

- [ ] **Step 3: Verify counts have not moved**

Run: `uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q`
Expected: 87 unit, 10 integration passed / 2 skipped — **identical to the end of Task 2**. This task is a pure refactor.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q && uv run lint-imports
git add -A && git commit -m "The harness leaves take the file system they use"
```

---

### Task 4: The entry points and the delegates

**Files:**
- Modify: `ancalagon/worker.py`, `ancalagon/cli.py`, `ancalagon/answer.py`, `ancalagon/supervisor/supervisor.py`, `ancalagon/supervisor/subprocess_spawner.py`, `ancalagon/tools/delegate/collect_task.py`, `ancalagon/tools/delegate/delegate_to.py`
- Test: extend existing tests only

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing new. This task ends with `RealFileSystem()` constructed exactly twice — once in `cli.main` and once in `worker.main` — and threaded from there.

The delegate tools work on `run_dir / "tasks" / ...`, which the harness builds, so they take the port directly rather than going through `Workspace`. They already receive `run_dir` and `clock` at construction; `fs` joins them.

`subprocess_spawner.py` has one `mkdir` and one `stderr.open("w")` — the latter becomes `fs.open_write(stderr)`. It already takes `Environment`; `fs` joins it.

- [ ] **Step 1: Thread the port from the two entry points**

Construct `RealFileSystem()` in `cli.main` and `worker.main`, and pass it down. `answer.py`'s `answer_task` takes one too, from `answer_command`.

- [ ] **Step 2: Confirm the package is clean**

```bash
grep -rn --include='*.py' -o '\.\(read_text\|write_text\|read_bytes\|mkdir\|unlink\|iterdir\|glob\|exists\|is_file\|is_dir\)(' ancalagon
```
Expected: hits **only** in `ancalagon/fs/real_file_system.py`. Any other hit is unfinished work — list it in the report rather than leaving it.

```bash
grep -rn --include='*.py' '\.open(' ancalagon
```
Expected: only `LifecycleStore.open` call sites, plus the two `open_*` definitions in the adapter.

- [ ] **Step 3: Verify counts have not moved**

Expected: 87 unit, 10 integration passed / 2 skipped, unchanged.

- [ ] **Step 4: Verify and commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q && uv run lint-imports
git add -A && git commit -m "One file system, built at the entry points"
```

---

### Task 5: The ban

**Files:**
- Modify: `precommit-scripts/check-ambient-access`

**Interfaces:**
- Consumes: a package with no raw file I/O outside the adapter, from Task 4.

Extend the **existing** script from the `Environment` plan rather than adding a second one. Read it first and match its structure exactly: `set -uo pipefail` without `-e`, `[ -n ... ]` rather than `[[ ]]`, a bracketed prefix on every line, a blank `echo ""` after each block, and the trailing `Clean.` line.

- [ ] **Step 1: Add the filesystem block**

```bash
FS_HITS=$(rg -n --type py '\.(read_text|write_text|read_bytes|mkdir|unlink|iterdir|glob|exists|is_file|is_dir)\(' ancalagon \
  --glob '!ancalagon/fs/real_file_system.py' 2>/dev/null)

OPEN_HITS=$(rg -n --type py '\.open\(' ancalagon \
  --glob '!ancalagon/fs/real_file_system.py' 2>/dev/null | rg -v 'Store\.open\(')
```

`tests/` is not scanned: `tmp_path` on real paths is correct there, and the guidelines say so.

The `OPEN_HITS` filter is why `LifecycleStore.open` keeps its name — see the spec. Do not rename it to satisfy the search.

- [ ] **Step 2: Prove the ban fires, three ways**

Run it on the clean tree and confirm exit 0.

Then plant each of these in turn, confirm exit 1 naming the file and line, and remove it:
1. `path.read_text()` in `ancalagon/clock/system_clock.py`
2. `path.open("w")` in `ancalagon/clock/system_clock.py`
3. A `LifecycleStore.open(...)` call left untouched — confirm it does **not** trip the ban.

Record all four outputs in the task report. The third is the one that matters: a ban that fires on the legitimate case gets disabled within a week.

- [ ] **Step 3: Full sweep and commit**

```bash
git add -A && uv run pre-commit run --all-files
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit -q && uv run python -m pytest tests/integration -q && uv run lint-imports
git commit -m "Touching a file outside the adapter fails the build"
```

Expected: all hooks pass, 87 unit, 10 integration passed / 2 skipped, contracts 4 kept.

---

## What this plan does not do

- No `FakeFileSystem`, and no change to `docs/guidelines/testing-patterns.md`. `tmp_path` stays.
- No `resolve` or `expanduser` behind the port, and neither is banned. Recorded in the spec's residuals.
- No `run_command` change. It still has no `cwd` and no `timeout` — a real defect, recorded and out of scope.
- No change to what `Workspace` scopes. `read_roots` and `write_root` mean what they mean today; this only changes how a tool reaches them.
