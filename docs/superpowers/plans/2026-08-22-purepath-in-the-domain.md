# PurePath in the Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make raw file I/O a type error outside the adapter, replacing the textual ban with a guarantee Pyright enforces at the point the mistake is written.

**Architecture:** Python already splits the two things `pathlib` does. `PurePath` is string manipulation with no syscalls; `Path` subclasses it and adds forty methods, every one a syscall. Annotating the domain with `PurePath` makes `path.read_text()` unrepresentable there, because the attribute does not exist on the type. `FileSystem` takes and returns `PurePath`; `RealFileSystem` is the one place that turns one into a `Path`.

**Tech Stack:** Python 3.13, `pathlib.PurePath`, Pyright strict, import-linter.

**Spec:** `docs/superpowers/specs/2026-08-22-ports-for-filesystem-and-environment-design.md`. This supersedes that spec's Enforcement section for the filesystem half: the ripgrep ban was written because "the calls to ban are methods, which the import graph cannot see". That is still true of the import graph, but the *type* checker can see them, and it is the stronger mechanism.

## Global Constraints

- Pyright strict, **zero errors**. `Any` and `object` banned; every generic parameterised.
- **No comments** except a one-line header on a class or module.
- **Delegate on a need basis.** `FileSystem` gains only what a caller actually needs — `resolve` and `expanduser`, and nothing else from `Path`'s forty methods. Do not mirror the stdlib surface.
- No `None` defaults or returns, no defensive guards, no bare `except`, no mocking.
- Never name an external codebase under analysis in any tracked artifact.
- **There is no bypass for the pre-commit hooks.** Never `git stash`.
- Counts at the start: **87 unit**, **10 integration passed / 2 skipped**, **contracts 6 kept**. This is a pure refactor: no count may move.
- Verify with: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`.

## What was established before writing this

- `set(dir(Path)) - set(dir(PurePath))` is exactly the forty syscall methods, `read_text` and `resolve` and `expanduser` among them. `PurePath` has none of them.
- Pyright rejects `p.read_text()` on a `PurePath` with `Cannot access attribute "read_text" for class "PurePath"`.
- `PurePath` is `os.PathLike`; `sqlite3.connect` accepts one; `subprocess` takes `str(p)`. The edges hold.
- `Path` is a subtype of `PurePath`, so `argparse(type=pathlib.Path)` still satisfies a `PurePath` annotation and `RealFileSystem` may return a `Path` where `PurePath` is declared.
- `ClassRef.module` is **already resolved** at both its sources — `config/load._root()` calls `.resolve()`, and `role.FREE_TEXT` uses `__file__`, which comes back resolved (checked at runtime). So `resolve_class`'s own `.resolve()` re-derives an upstream decision.

---

### Task 1: The port speaks PurePath, and gains the two syscalls the domain still needs

**Files:**
- Modify: `ancalagon/fs/file_system.py`, `ancalagon/fs/real_file_system.py`
- Test: `tests/unit/test_file_system.py`

**Interfaces:**
- Produces: every `FileSystem` method takes `pathlib.PurePath`; `iterdir`/`glob` return `tuple[pathlib.PurePath, ...]`; two new methods:

```python
def resolve(self, path: pathlib.PurePath) -> pathlib.PurePath: ...
def expanduser(self, path: pathlib.PurePath) -> pathlib.PurePath: ...
```

`RealFileSystem` is the only place that constructs a `Path`. Every method converts on entry:

```python
    def read_text(self, path: pathlib.PurePath) -> str:
        return pathlib.Path(path).read_text(encoding="utf-8")
```

`resolve` and `expanduser` are added because 9 call sites in 5 files need them and `PurePath` does not have them. Nothing else from `Path` is added.

- [ ] **Step 1: Extend the existing test**

Add to the single test in `tests/unit/test_file_system.py` — do not create a second test:

```python
    assert fs.resolve(nested / ".." / "b") == nested
    assert str(fs.expanduser(pathlib.PurePath("~"))).startswith("/")
```

- [ ] **Step 2: Run it to confirm it fails**

Expected: `AttributeError: 'RealFileSystem' object has no attribute 'resolve'`.

- [ ] **Step 3: Change both files**

Every `pathlib.Path` annotation in the protocol and the adapter becomes `pathlib.PurePath`. The adapter's bodies wrap in `pathlib.Path(path)`. Add the two methods.

- [ ] **Step 4: Verify**

Run: `uv run python -m pytest tests/unit/test_file_system.py -q`. Pyright will now report errors across the package; that is Task 2's work.

---

### Task 2: The domain speaks PurePath

**Files:**
- Modify: every module under `ancalagon/` annotating `pathlib.Path`, except `ancalagon/fs/real_file_system.py`
- Modify: `ancalagon/workspace/workspace.py` — its four `.expanduser().resolve()` calls delegate to `self.fs`
- Modify: `ancalagon/config/load.py`, `ancalagon/cli.py` — their `.resolve()` calls delegate to their `fs`
- Modify: `ancalagon/contracts/resolve.py` — delete the redundant `.resolve()`
- Modify: the tests, which annotate `pathlib.Path` in ~124 places

**Interfaces:**
- Consumes: Task 1's port.
- Produces: `pathlib.Path` appears in `ancalagon/` only inside `real_file_system.py`.

`contracts/resolve.py` may **not** take a `FileSystem`: `contracts` is a bottom-layer leaf and the independence contract forbids it. Its `.resolve()` is deleted rather than delegated, because both callers already hand it a resolved path. This is the codebase's own rule — pass decisions through data, do not re-derive downstream.

`migrations.DIRECTORY` stays a `pathlib.Path(__file__).parent / "migrations"`: it is built from `__file__` at import time in the module that owns the `.sql` files, and it is passed straight to `fs.glob`. Annotate it `pathlib.PurePath`.

- [ ] **Step 1: Substitute the annotations**

`pathlib.Path` → `pathlib.PurePath` across `ancalagon/` and `tests/`, excluding `real_file_system.py`. This is a textual substitution of a type name, not an argument insertion — it cannot produce the unbalanced-paren corruption an argument insertion can. Verify with `uv run python -m black --check .` that every file still parses.

- [ ] **Step 2: Fix what Pyright then names**

Run `uv run pyright` and work the list. Expect three kinds: `Workspace`'s resolve calls, `config/load`'s and `cli`'s resolve calls, and `argparse(type=...)`. Do not silence any of them with a cast.

- [ ] **Step 3: Delete the redundant resolve**

`contracts/resolve.py`: `path = pathlib.PurePath(ref.module)`.

- [ ] **Step 4: Prove the guarantee**

Add `return args.path.read_text()` to `ancalagon/tools/files/read_file.py`, run `uv run pyright`, and confirm `Cannot access attribute "read_text" for class "PurePath"` **reported at that line**. Revert. Record the message in the report. This is the whole point of the change; if it does not hold, stop.

- [ ] **Step 5: Verify counts have not moved**

87 unit, 10 integration passed / 2 skipped, 6 contracts. Any change is a finding, not an assertion to edit.

---

### Task 3: Retire the textual half of the ban

**Files:**
- Modify: `precommit-scripts/check-ambient-access`

The filesystem block and the `.open(` block are deleted; the `os.environ` block stays. Pyright now enforces what the regex approximated, at the point the mistake is written rather than at commit time, with no receiver-name carve-out and no way to defeat it by binding the method to a name.

- [ ] **Step 1: Delete the two blocks, keep the environment one**

- [ ] **Step 2: Confirm the environment ban still fires**

Plant `os.environ.get("X", "")` in `ancalagon/clock/system_clock.py`, confirm exit 1, remove it, confirm exit 0.

- [ ] **Step 3: Confirm nothing else regressed**

Full `uv run pre-commit run --all-files`, both suites, `lint-imports`.

---

## What this does not change

- The `Environment` port and its ban are untouched.
- The import contract forbidding the seven tool packages from importing `ancalagon.fs` stays. It answers a different question — who may hold the port — which the type system does not.
- `Workspace` keeps `resolve_read`/`resolve_write` public, and keeps scoping. Nothing about what it permits changes.
