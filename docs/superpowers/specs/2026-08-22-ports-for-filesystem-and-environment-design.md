# Ports for the filesystem and the environment

## The problem

The previous branch put SQL behind two adapters and made the rule machine-checked. Two ambient
dependencies were left untouched, and a sweep of `ancalagon/` found them.

`os.environ` is read once, at `supervisor/subprocess_spawner.py:45`:

```python
env={**os.environ, **self.sandbox.environment()},
```

Nothing curates it. `Fence.environment()` and `Unsandboxed.environment()` both return `{}`, so a
worker inherits the launching shell entire. This surfaced through a test: with `GIT_DIR` exported —
which is what `git commit` does to its hooks — `git -C <dir> log` inside a tool reads the wrong
repository. That is not reachable in production, because nothing launches the harness from a git
hook, but the propagation path is real and unguarded.

The filesystem is the larger gap, and the more surprising one, because it looks solved. `Workspace`
is a **path authority**, not an I/O port: `resolve_read` and `resolve_write` answer "may I touch
this path" and hand back a resolved `pathlib.Path`. The caller then reads it. **44 call sites
across 22 files** then do their own `read_text`, `write_text`, `mkdir` and `unlink` — 14 of them
tool-facing and reachable through `Workspace`, the other 30 harness-internal, on paths the harness
builds rather than paths a model supplies.

Every agent-facing tool does resolve first — all seventeen were checked, and there is no bypass
today. But that is a convention each tool re-enacts, not an invariant. A tool that forgets to
resolve is scoped to nothing, and nothing fails.

## What is already behind a port

Stated so the gap is legible against it. Time is `Clock`, with `SystemClock` and `FakeClock`.
Model access is the `LLM` protocol with a LiteLLM adapter. Process spawning is `Spawner` and
`Process`. SQLite is `connect` plus the two stores. There is no `uuid`, no `random`, no
`os.getcwd`, no `sys.argv`, and no socket anywhere in the package.

The four remaining `sys.stdout`/`sys.stderr` writes are all in CLI entry points, which is where
they belong. They are not in scope.

## The two ports

**`ancalagon/fs/file_system.py`** — a `FileSystem` protocol, with `real_file_system.py` as its
only adapter. The surface is exactly what the sweep found in use, and nothing more:

| Group | Operations |
|---|---|
| Content | `read_text`, `write_text`, `read_bytes` |
| Structure | `mkdir(path, parents, exist_ok)`, `unlink` |
| Listing | `iterdir`, `glob(path, pattern)` — `glob` is used only by `migrations` |
| Predicates | `exists`, `is_file`, `is_dir` |
| Handles | `open_append`, `open_write` — both returning `typing.TextIO` |

`resolve` was on this list and has been removed. It reads no content and writes nothing; it
normalises a path and follows symlinks in components that already exist. Putting it behind the port
would add nine call sites and force a `FileSystem` into `Workspace.__init__` and
`contracts/resolve.py` purely to normalise strings, without changing what can go wrong. It joins
`expanduser` in the residuals.

**`ancalagon/env/environment.py`** — an `Environment` protocol with one method returning
`Mapping[str, str]`, and `real_environment.py` wrapping `os.environ`. It is injected into
`SubprocessSpawner`, which is its only consumer.

## Workspace becomes the filesystem's scoped face

`Workspace` takes a `FileSystem` at construction and gains the scoped operations, each resolving
before it delegates:

```python
def read_text(self, path: pathlib.Path) -> str:
    return self.fs.read_text(self.resolve_read(path))
```

This is the point of the exercise. Once reading is only reachable through the scoped method,
scoping stops being a convention a tool can forget and becomes the only way through.

`resolve_read` and `resolve_write` stay public. `ripgrep`, `ast_grep`, `find_symbol` and
`code_stats` need the resolved path as a string to hand to a subprocess, not its contents.

## What this deliberately does not do

**No fake filesystem.** `docs/guidelines/testing-patterns.md` sanctions `pytest`'s `tmp_path` for
filesystem tests, and that stays. `RealFileSystem` is the only adapter that will exist. The port's
payoff is therefore stated honestly and narrowly: it names the dependency, makes it injectable,
gets raw I/O out of the domain, and gives the ban below something to point at. It does not make
`worker.py` or `cli.py` testable without a disk, and it is not a step toward that.

**No subprocess port.** `run_command` stays as it is. Whether wrapping `subprocess.run` earns its
overhead is undecided, and deciding it is not this change.

**No new configuration.** Neither port is selectable. There is one adapter for each, constructed at
the entry points.

## Enforcement

The SQL contract's mechanism does not transfer. `import-linter` can forbid `sqlite3` because
`sqlite3` has no use except SQL; `pathlib.Path` is a value type that nearly every module
legitimately uses to *build* paths (`.name`, `.parent`, `/`). Forbidding the import is impossible,
and the calls to ban are methods, which the import graph cannot see.

`precommit-scripts/check-filesystem-access` follows the pattern `check-type-hygiene` already
establishes — a ripgrep script for a syntactic rule the type checker cannot express. It bans the
eleven `pathlib` methods those operations wrap — `read_text`, `write_text`, `read_bytes`, `mkdir`,
`unlink`, `iterdir`, `glob`, `exists`, `is_file`, `is_dir`, `open` — outside
`ancalagon/fs/real_file_system.py`, and excludes `tests/`, where `tmp_path` on real paths remains
correct.

A matching line in the same script bans `os.environ` and `os.getenv` outside
`ancalagon/env/real_environment.py`.

## The layering

`migrations` is currently the lowest layer and it globs and reads its `.sql` files, so it needs
`FileSystem`. The ports therefore go *beneath* it, as a new bottom line:

```toml
"ancalagon.contracts : ancalagon.clock : ancalagon.sandbox",
"ancalagon.migrations",
"ancalagon.fs : ancalagon.env",
```

Both are added to the existing `Sibling leaves are independent` contract. `fs` imports only
`pathlib` and `typing`; `env` imports only `os` and `collections.abc`. Neither imports the other.

## Decisions

**Text is UTF-8, always.** The port takes no `encoding` parameter. Call sites are currently
inconsistent — `worker.py:140` uses the platform default, `transcript` and the file tools pass
`encoding="utf-8"` — and unifying on UTF-8 removes the parameter rather than propagating the
inconsistency. On the platforms this runs on the two already agree, so no behaviour changes.

**`LifecycleStore.open` keeps its name.** A textual ban on `.open(` collides with it: of the nine
`.open(` calls in the package, seven are `LifecycleStore.open` and only two are real file handles
(`transcript.py`, `subprocess_spawner.py`). The script excludes `Store.open(` explicitly rather than renaming a well-named factory to
satisfy a text search. This goes the opposite way to `Transcript.append`, which was renamed to
`write` for a lint false positive last week: that rename also read better, and this one would not.

**Threading is the bulk of the diff.** `worker.py`, `cli.py` (including `init_command` and
`created_run_dir`), `transcript`, `config/load`, `migrations`, `sandbox/fence.py` and
`bus/connect.py` each gain a `FileSystem` parameter, threaded from their entry point. This buys explicitness, not new tests, and the plan should not pretend
otherwise.

## Residuals

- `Path.expanduser()` reads `HOME` from the environment, so it is strictly environment access
  wearing a filesystem shape. It stays on `pathlib` and outside the ban. Routing it through
  `Environment` would mean reimplementing `expanduser`, which is worse than the leak.
- `Path.resolve()` stays on `pathlib` too, for the reason given above.
- `run_command` still inherits the environment it is given, has no `cwd`, and has no `timeout`. A
  hung `rg` or `git` blocks its worker indefinitely with nothing to reap it. That is a real defect
  and it is out of scope here; it is recorded so it is not rediscovered.
- The ban is textual. A module that binds `read = path.read_text` and calls `read()` defeats it.
  No mechanism available here catches that, and it is not worth defending against.
