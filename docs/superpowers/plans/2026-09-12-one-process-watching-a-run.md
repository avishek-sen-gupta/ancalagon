# One Process Watching A Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ancalagon watch` follows every agent in a run from one process, instead of `scripts/ancwatch.zsh`'s two processes per transcript.

**Architecture:** A poller gated on `changed_at`, a watermark per agent, and a pure renderer. It follows `trace_command.py` + `ancalagon/trace/graph_of.py`: a command module at the top, the units it uses in a package beside it.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** none — settled by investigation, recorded below.

## Why, and what was measured

`scripts/ancwatch.zsh` globs `$root/runs/*/tasks/*/transcript.jsonl` and starts a `tail -f | jq`
pair per match. On a workspace with 7 run directories and 22 transcripts that is **44 long-lived
processes at startup**, 22 of them running the jq filter against files that will never grow again.
Nothing is ever reaped, so a long session only accumulates more.

Measured on that workspace (642 KB, 658 messages) before choosing this design:

| operation | cost |
|---|---|
| parse every transcript | 14.5 ms |
| `stat` every transcript | 0.15 ms |

So a single process that stats all transcripts each second and re-reads only the ones whose mtime
moved costs 0.15 ms/sec at rest. Even re-parsing everything every second is about 1.5% of one core.
That is why this design needs no byte offsets: `FileSystem` has no seek, and only
`real_file_system.py` may touch a file, so offsets would have meant extending the port. A
per-agent `seq` high-water mark is enough and is what gives the correct new-versus-existing
behaviour that the shell script gets wrong — it prints
`-- N existing agent(s) skipped --` while in fact tailing all N.

## Naming, because two things here are called watch

`ancalagon/watch/` is the deterministic `watch_for` runner, and `watch_file` is a tool an agent
calls. Neither has anything to do with this. The subcommand is `ancalagon watch`, its command
module is `ancalagon/watch_command.py`, and its units live in `ancalagon/watching/`. Any
documentation this plan touches must keep `ancalagon watch` and `watch_file` apart in the reader's
mind rather than assume the context makes it obvious.

## Global Constraints

- Pyright strict, ZERO errors. `Any`, `object` annotations and hand-rolled JSON types are banned.
- Every generic parameterised. All pydantic models `frozen=True`. One class per file. No static methods.
- NO COMMENTS except a single one-line header at the top of a module or class. No docstrings.
- No defensive programming, no `None` defaults, no `None` returns — null object pattern instead.
- Mutable state only in the shell. The watermark map is shell, and the class holding it must say so in its header the way `Session` and `ToolContext` do.
- Fully qualified imports, no relative imports. After editing imports run `uv run ruff check --select I --fix ancalagon/ tests/`.
- python-fp-lint: complexity ≤ 3 per function, no `list.append`, no loop that mutates an accumulator, no `print` (ruff `T20` — use `sys.stdout.write`, as `ancalagon/emit.py` does).
- Injected dependencies only: `FileSystem` for every file touch, `Clock` for `sleep`. No `time.sleep`, no `pathlib.Path` reads.
- Few tests, each covering a whole behaviour, with concrete value assertions.
- Assertions are sacred. Do not weaken or delete an existing one; a newly failing one is a finding.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`. Full integration suite every task.
- Talisman: APPEND an entry for a newly flagged file, REPLACE THE CHECKSUM IN PLACE for one already listed. Verify each commit with `git log --oneline -1`.
- `scripts/ancwatch.zsh` is NOT deleted by this plan. That decision comes after this has earned its keep.

---

### Task 1: Render one message

**Files:**
- Create: `ancalagon/watching/rendered.py`
- Test: `tests/unit/test_watching.py`

**Interfaces:**
- Produces: `rendered(label: str, message: Message, width: int) -> str`

This is the functional core: no I/O, no state. It replaces `scripts/ancwatch.jq`, which is seven
lines. Read that file first — it is the specification of the output format, and the format should
not change in this task.

- [ ] **Step 1: Write the failing test**

`ancwatch.jq` renders a header line then one line per block. Its three branches map exactly onto
the `Block` union (`Text | ToolUse | ToolResultBlock`), so this is `isinstance` dispatch rather
than reading a `kind` string.

```python
def test_a_message_renders_a_header_and_one_line_per_block():
    message = Message(
        role=MessageRole.ASSISTANT,
        blocks=[
            Text(text="looking now"),
            ToolUse(id="tu_0", name="read_file", arguments='{"path": "/w/a.md"}'),
            ToolResultBlock(tool_use_id="tu_0", content="payload", is_error=False),
            ToolResultBlock(tool_use_id="tu_1", content="outside the read roots", is_error=True),
        ],
        agent=3,
        seq=7,
        ts="2026-09-12T10:00:00Z",
    )

    lines = rendered("r_1/root", message, width=40).splitlines()

    assert lines[0] == "[36m[r_1/root/3][0m A"
    assert lines[1] == "  looking now"
    assert lines[2] == '  → [1;33mread_file[0m {"path": "/w/a.md"}'
    assert lines[3] == "  ← payload"
    assert lines[4] == "  ← [31mERR[0m outside the read roots"
```

Check every one of those strings against `scripts/ancwatch.jq` before writing the implementation —
the escape codes, the arrows, the two-space indent and the single-letter uppercase role. If the
jq filter disagrees with this test, **the jq filter wins** and you fix the test, because the point
is that the output does not change. Say in your report what you had to correct.

- [ ] **Step 2: Add the truncation and newline behaviour to the same test**

One behaviour, one test — extend it rather than adding a second:

```python
    long = Message(
        role=MessageRole.USER,
        blocks=[Text(text="x" * 500), ToolUse(id="t", name="shell", arguments="y" * 500)],
        agent=1,
        seq=1,
        ts="2026-09-12T10:00:00Z",
    )
    wide = rendered("r_1/root", long, width=10).splitlines()

    assert wide[0] == "[36m[r_1/root/1][0m U"
    assert wide[1] == "  " + "x" * 40
    assert wide[2] == "  → [1;33mshell[0m " + "y" * 10
```

`ancwatch.jq` truncates text at `width*4` and tool arguments and results at `width`, and replaces
newlines inside a block. Confirm both multipliers in the filter before pinning them here.

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run python -m pytest tests/unit/test_watching.py -v`
Expected: FAIL — `rendered` does not exist.

- [ ] **Step 4: Write it**

`ancalagon/watching/rendered.py`, one module-level function, no class. Complexity ≤ 3 means the
per-block branch belongs in its own small function, not nested inside a loop inside `rendered`.
Build the output with a comprehension and `"".join`, never `list.append`.

- [ ] **Step 5: Run the test, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon/watching tests/unit/test_watching.py
git commit -m "$(cat <<'EOF'
Render a transcript message without jq

The three branches of ancwatch.jq are the three members of the Block
union, so the renderer dispatches on the type rather than on a string
the filter had to read back out of the JSON.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The watcher

**Files:**
- Create: `ancalagon/watching/watch.py`
- Modify: `pyproject.toml` — three contracts
- Test: `tests/unit/test_watching.py`

**Interfaces:**
- Consumes: `rendered` from Task 1.
- Produces: `Watch(write_root, fs, clock, width)` with
  - `tick() -> str` — one pass: everything new since the last call
  - `follow(interval_s: float) -> None` — `tick`, write, `clock.sleep`, repeat

`Watch` is shell: it holds the watermark map and it advances. Say so in its one-line header.

- [ ] **Step 1: Write the failing test**

Three behaviours, three tests, all driven through `tick()` so no loop ever runs in a test.

```python
def test_agents_present_at_the_first_tick_show_nothing_of_their_history(tmp_path):
    _transcript(tmp_path, "r_1", "root", [_text(1, "old news")])
    watch = Watch(pathlib.PurePath(tmp_path), RealFileSystem(), FakeClock(), width=40)

    assert watch.tick() == ""


def test_an_agent_that_appears_later_is_shown_from_its_first_message(tmp_path):
    watch = Watch(pathlib.PurePath(tmp_path), RealFileSystem(), FakeClock(), width=40)
    watch.tick()
    _transcript(tmp_path, "r_1", "root", [_text(1, "hello")])

    shown = watch.tick()

    assert "hello" in shown
    assert "[r_1/root/1]" in shown


def test_a_tick_shows_only_what_arrived_since_the_last_one(tmp_path):
    watch = Watch(pathlib.PurePath(tmp_path), RealFileSystem(), FakeClock(), width=40)
    watch.tick()
    _transcript(tmp_path, "r_1", "root", [_text(1, "first")])
    watch.tick()
    _append(tmp_path, "r_1", "root", _text(2, "second"))

    shown = watch.tick()

    assert "second" in shown
    assert "first" not in shown
    assert watch.tick() == ""
```

Write `_transcript`, `_append` and `_text` as small local helpers that write real JSONL under
`tmp_path/runs/<run>/tasks/<task>/transcript.jsonl` using `Message(...).model_dump_json()`. Do not
hand-write JSON strings — the model is the contract.

**One hazard to handle in the helpers:** `changed_at` is `st_mtime`, whose resolution can be
coarse enough that two writes within the same tick look unchanged. If a test proves flaky, make
the helper advance the file's mtime explicitly rather than sleeping, and say so in your report.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run python -m pytest tests/unit/test_watching.py -v`
Expected: FAIL — `Watch` does not exist.

- [ ] **Step 3: Write it**

```python
class Watch:
    def __init__(self, write_root, fs, clock, width):
        self.seen: dict[str, int] = {}
```

`tick()`:
1. `self.fs.glob(self.write_root, "runs/*/tasks/*/transcript.jsonl")` — `RealFileSystem.glob`
   delegates to `pathlib.Path.glob` and sorts, so ordering is deterministic.
2. For each path, skip it when `fs.changed_at(path)` is not greater than the mtime recorded for it.
   `changed_at` returns `0.0` for a missing file rather than raising, so no guard is needed.
3. For a file seen for the first time *after construction*, the watermark starts below its lowest
   `seq` so everything shows; for one present at construction, the watermark starts at its highest
   `seq` so nothing does. The constructor establishes the second case.
4. `load(fs, path)` and render every message whose `seq` exceeds the watermark, then raise it.

The label is `<run-dir>/<task-dir>` and the agent number comes off `message.agent`, matching what
the shell script built from path components.

Complexity ≤ 3 per function: `tick` coordinates, and the per-file work belongs in its own method.

- [ ] **Step 4: Add the three contract entries**

In `pyproject.toml`:
- `"Layers point downward"` — insert two lines between `"ancalagon.trace",` and `"ancalagon.worker",`:
  ```toml
      "ancalagon.watch_command",
      "ancalagon.watching",
  ```
  They are separate lines, not `a : b`. The `:` form means independent siblings that may not
  import each other, and `watch_command` imports `watching`.
- The two `forbidden` contracts whose `source_modules` list every package — add
  `"ancalagon.watch_command",` and `"ancalagon.watching",` in alphabetical position to **both**.
  They sort after `"ancalagon.watch"`.

- [ ] **Step 5: Run everything, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon tests pyproject.toml
git commit -m "$(cat <<'EOF'
Follow every agent in a run from one process

The shell watcher starts a tail and a jq per transcript: 44 processes on
a workspace with 22 of them, and it never reaps one. Statting them all
costs 0.15ms and parsing all of them costs 14.5ms, so one process that
re-reads only what moved is cheaper than the pipes were.

A watermark per agent also gets the semantics right. The shell script
says it skips the agents already on disk and then tails all of them.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The subcommand

**Files:**
- Create: `ancalagon/watch_command.py`
- Modify: `ancalagon/cli.py` — parser and dispatch
- Modify: `README.md`, `docs/architecture.md`
- Test: `tests/unit/test_watching.py`

**Interfaces:**
- Consumes: `Watch` from Task 2.
- Produces: `watch_command(config_path, fs, clock, interval_s) -> int`

- [ ] **Step 1: Write the failing test**

The command's own behaviour is resolving a config to a write root and building a `Watch` over it —
`follow` loops forever and is not what a unit test should call.

```python
def test_the_command_watches_the_write_root_its_config_names(tmp_path):
    ...write a config TOML whose write_root is tmp_path/"ws"...
    watching = watch_for_config(pathlib.PurePath(config_path), RealFileSystem())

    assert watching.write_root == pathlib.PurePath(tmp_path / "ws")
```

Split the resolution out as `watch_for_config(config_path, fs) -> Watch` so it is testable without
entering the loop, and have `watch_command` call it then `follow`. Read `load_config` first:
relative roots resolve against the **config file**, not the process cwd, and that is the behaviour
this test pins.

- [ ] **Step 2: Run it and watch it fail, then write it**

`watch_command.py` mirrors `trace_command.py`'s shape. Width comes from
`shutil.get_terminal_size()`; `ancalagon/emit.py` already writes to `sys.stdout` directly, so a
command doing the same needs no new port. `follow` writes each non-empty `tick()` and sleeps
through the injected `Clock`.

- [ ] **Step 3: Wire the subcommand**

In `cli.py`, beside `trace` and `viz`:

```python
    watch = commands.add_parser("watch")
    watch.add_argument("--config", type=pathlib.PurePath, required=True)
    watch.add_argument("--interval", type=float, default=1.0)
```

and the matching dispatch line. `KeyboardInterrupt` is how an operator stops it — let it propagate
rather than catching it; `Session.run` deliberately lets it through for the same reason.

- [ ] **Step 4: Document it, keeping the two watches apart**

`README.md` gains `ancalagon watch` where the other subcommands are described, and must say plainly
that it is unrelated to the `watch_file` tool. `docs/architecture.md` gains it beside `trace`.
Verify every claim against the code before committing it — this repo has shipped four false
documentation claims already, three of which were caught only in review.

State the measured numbers rather than adjectives: one process against two per transcript, and why
polling is affordable.

- [ ] **Step 5: Run it for real**

```bash
uv run python -m ancalagon.cli watch --config ancalagon.toml
```

against the existing `./ws`, which has 7 run directories and 22 transcripts. Confirm it starts
silently (all history is old), and that `ps` shows one process where the shell script would show
44. Report what you saw. Do NOT delete `scripts/ancwatch.zsh`.

- [ ] **Step 6: Full verification, then commit**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
git add ancalagon tests README.md docs/architecture.md .talismanrc
git commit -m "$(cat <<'EOF'
Add ancalagon watch

One process follows every agent in a run. Unrelated to the watch_file
tool and to ancalagon/watch, which are an agent's tool and the
deterministic runner behind it; the README says so, because the name
does not.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- `scripts/ancwatch.jq` is the specification of the output format in Task 1. Where it and this plan disagree, the filter wins.
- Never use `time.sleep` or `pathlib.Path` reads: `Clock` and `FileSystem` are injected for exactly this.
- Do not delete or modify `scripts/ancwatch.zsh`. That decision is deferred until this has been used.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix.
