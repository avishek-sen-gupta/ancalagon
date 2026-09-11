# One Agent In Your Process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a host program run one agent in its own process by handing over a `Config`, instead of copying fifty lines out of `worker.py`.

**Architecture:** The assembly moves into `ancalagon/session_for.py` — the tool catalogue, the registry builder, and `session_for` itself. `worker.main` becomes its first caller, passing real collaborators where an embedder takes the null-object defaults, so exactly one place knows how a `Session` is wired.

**Tech Stack:** Python 3.13, uv, pydantic, pytest, Pyright strict, import-linter, python-fp-lint.

**Spec:** `docs/superpowers/specs/2026-09-12-one-agent-in-your-process-design.md`

## A structural fact the spec did not account for

`build_registry`, `available_tools` and `watcher_in` live **inside `worker.py`**. `session_for` needs `build_registry`, and `worker.main` needs `session_for` — so putting `session_for` in its own module while leaving the registry builder in `worker.py` is a circular import.

Task 1 therefore moves all three into `ancalagon/session_for.py` first, and Task 2 adds `session_for` beside them. One module holds the whole assembly, which mirrors `ancalagon/run.py` — that file already groups `run`, `root_spec`, `sandbox_of`, `_spawner` and the goal helpers at a similar size.

`worker.py` loses about ninety lines and keeps only what a process needs: argument parsing, reading `spec.json`, opening the bus, writing the outcome, and the `except` that catches what escapes.

## Global Constraints

- Pyright strict, ZERO errors. `Any` is banned outright — no `typing.Any`, no `dict[str, Any]`, no `object` annotations, no hand-rolled JSON aliases.
- Every generic parameterised: `dict[str, int]` not `dict`; `Sequence`, `Mapping`, `tuple` equally.
- NO COMMENTS except a single one-line header at the top of each module or class. No docstrings on functions, no inline explanations, no section dividers, no TODOs.
- All pydantic models `frozen=True`. Fully qualified imports, no relative imports. One class per file. No static methods.
- A class implementing a Protocol **inherits** it.
- No defensive programming: no `None` checks masking bugs, no bare `try/except`, no workaround guards. No `None` defaults, no `None` returns from non-`None` return types — use the null object pattern.
- No `for` loops that mutate an accumulator; comprehensions, `map`, `filter` instead.
- python-fp-lint forbids `list.append(...)` and caps cyclomatic complexity at 3 per function. It also enforces import ordering — after editing imports run `uv run ruff check --select I --fix ancalagon/ tests/`.
- `fp.json` currently excludes `ancalagon/worker.py`. Code moved out of it lands in a file that is NOT excluded, so it must satisfy the linter. If moved-verbatim code fails, report the exact rule rather than adding a new exclusion without saying so.
- Refusal is a value, not an exception: a tool reports failure through `ctx.failure`, never by raising.
- Tests: few tests, each covering a whole behaviour, with concrete value assertions — never `assert x is not None` where a concrete value is available.
- No mocking (`unittest.mock` banned). `NO_BUS` and `FakeLLM` are the injected fakes.
- Assertions are sacred: do not weaken or delete an existing assertion. If one now fails, that is a finding to report.
- Verification per task: `uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports`. Run the FULL integration suite on every task — about 70 seconds. An earlier plan in this repo shipped a regression because a task skipped it.
- Do NOT use `python -c` with multiline strings. Write a script into the scratchpad and run `uv run python <path>`.
- Talisman may flag markdown prose as a false-positive secret. Reword when incidental; otherwise APPEND a `.talismanrc` entry for a newly flagged file, or REPLACE THE CHECKSUM IN PLACE for one already listed. Never duplicate a filename.

---

### Task 1: Move the assembly out of the worker

**Files:**
- Create: `ancalagon/session_for.py` — receives `available_tools`, `build_registry`, `watcher_in` and their private helpers
- Modify: `ancalagon/worker.py` — loses those three and their now-unused imports
- Modify: `ancalagon/check_contracts.py` — imports `build_registry` from its new home
- Modify: `pyproject.toml` — one new layer entry
- Test: `tests/unit/test_answer_file.py`, `test_watch.py`, `test_hooks.py`, `test_tools.py`, `test_session_loop.py` — import path only

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces, all unchanged in signature, only in location:
  - `available_tools(role, roles, run_dir, parent, output_class, clock, fs, web, bus) -> list[BoundTool]`
  - `build_registry(config, spec, run_dir, parent, depth, output_class, clock, fs, web, bus) -> Registry`
  - `watcher_in(roles) -> list[Role]`

This task is a PURE MOVE. No signature changes, no behaviour changes, no new tests. The existing suite is the safety net: if it passes, the move is faithful.

- [ ] **Step 1: Read what moves**

```bash
grep -nE "^def (available_tools|build_registry|watcher_in)|^def _(delegate|idle|watch)" ancalagon/worker.py
```

Move those functions and every private helper they call. `_idle` and `_watch` are the construction helpers added by an earlier plan — they go too. Read the whole of `worker.py` before cutting, so you take the imports each one needs and leave the ones `main` still uses.

- [ ] **Step 2: Create the new module**

`ancalagon/session_for.py`, with this exact one-line header and nothing else by way of comment:

```python
# How one agent is assembled: the tools it may call, and the session that calls them.
```

Move the three public functions and their helpers in verbatim, with their imports. Do not reformat, rename, or "improve" anything — a later reviewer compares this against the original.

- [ ] **Step 3: Verify nothing was left behind**

```bash
grep -nE "available_tools|build_registry|watcher_in|^def _idle|^def _watch" ancalagon/worker.py
```
Expected: only the `from ancalagon.session_for import build_registry` line `main` now needs.

- [ ] **Step 4: Add the layer entry**

In `pyproject.toml`, in the `"Layers point downward"` contract, the current entries read:

```toml
    "ancalagon.worker : ancalagon.watch",
    "ancalagon.supervisor : ancalagon.session",
```

Replace those two lines with three:

```toml
    "ancalagon.worker",
    "ancalagon.session_for : ancalagon.watch",
    "ancalagon.supervisor : ancalagon.session",
```

`ancalagon.watch` moves down beside `session_for` because `watcher_in` imports `WATCH_FOR` from `ancalagon/watch/watch_for.py`, and that module imports only `ancalagon.contracts` and `ancalagon.deterministic` — both lower still, so nothing breaks.

Two further contracts list every package by name — `"The database is reached only by the adapter that owns it"` and `"The process is reached only by the adapters that own it"`, whose `source_modules` both contain `"ancalagon.worker"`. Code moving out of `worker.py` leaves their coverage unless the new module is listed too. Add `"ancalagon.session_for",` to **both** lists, in alphabetical position — immediately after `"ancalagon.session",`. Neither contract's meaning changes; this only keeps the moved code under the same two bans it was under before.

- [ ] **Step 5: Fix every importer**

Six files import at least one of the three. Find them rather than trusting a list:

```bash
grep -rln "build_registry\|available_tools\|watcher_in" ancalagon tests --include="*.py" | grep -v pycache
```

Each changes `from ancalagon.worker import ...` to `from ancalagon.session_for import ...`. Nothing else about those files changes — no assertion, no argument, no call.

- [ ] **Step 6: Run the tests**

```bash
uv run python -m pytest tests/unit -v
```
Expected: PASS, with the same count as before the move. A failure here is a moved import you missed, not a behaviour change.

- [ ] **Step 7: Check the linter that no longer skips this code**

```bash
uv run python -m black . && uv run pyright && uv run lint-imports
```

`fp.json` excludes `ancalagon/worker.py` but not `ancalagon/session_for.py`, so python-fp-lint now inspects code it previously skipped. The pre-commit hook runs it. If it flags moved-verbatim code, report the exact rule and line in your report — do NOT add `ancalagon/session_for.py` to `fp.json` without saying so explicitly and explaining why the code cannot satisfy the rule.

- [ ] **Step 8: Full verification**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 9: Commit**

```bash
git add ancalagon tests pyproject.toml
git commit -m "$(cat <<'EOF'
Move how an agent is assembled out of the worker

build_registry lived in worker.py, so anything that builds a session had
to import from the module that runs one as a process. The tool catalogue
and the registry builder move to their own home, and worker keeps only
what a process needs.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The entry point

**Files:**
- Modify: `ancalagon/session_for.py` — add `session_for` beside the registry builder
- Modify: `ancalagon/worker.py` — `main` calls it
- Test: `tests/unit/test_session_for.py`

**Interfaces:**
- Consumes: `build_registry` from Task 1.
- Produces:

```python
def session_for(
    config: Config,
    spec: TaskSpec,
    ctx: ToolContext,
    transcript: Transcript,
    run_dir: pathlib.PurePath,
    llm: LLM,
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
    bus: Bus = NO_BUS,
    children: Children = NO_CHILDREN,
    letterbox: Letterbox = NO_LETTERBOX,
    meter: Meter = UNMETERED,
    depth: int = 0,
) -> Session
```

Nine required, five defaulted.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_session_for.py`. The behaviour: taking every default gives a session that cannot reach a bus.

```python
def test_a_session_with_no_bus_gets_tools_that_cannot_queue(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    write_root = tmp_path / "ws"
    task_dir = write_root / "tasks" / "solo"
    fs.mkdir(pathlib.PurePath(task_dir), parents=True, exist_ok=True)
    config = Config(
        write_root=pathlib.PurePath(write_root),
        read_roots=(pathlib.PurePath(write_root),),
        model="some-provider/no-model-is-called",
        roles={"solo": SOLO},
    )
    spec = TaskSpec(task_id="solo", role=SOLO, goal="Answer it.")
    ctx = ToolContext(
        workspace=Workspace.from_config(config, fs),
        task_dir=pathlib.PurePath(task_dir),
        summary_chars=config.summary_chars,
        agent_id=1,
        input=FreeText(text="Answer it."),
    )
    transcript = Transcript(fs, path=pathlib.PurePath(task_dir / "transcript.jsonl"), agent_id=1)

    session = session_for(
        config,
        spec,
        ctx,
        transcript,
        pathlib.PurePath(tmp_path / "runs" / "solo"),
        FakeLLM([]),
        FakeClock(),
        fs,
        RealWebClient(),
    )
    transcript.close()

    assert isinstance(session.registry.get("delegate_solo").invoke, object)
    assert session.children is NO_CHILDREN
    assert session.letterbox is NO_LETTERBOX
    assert session.meter is UNMETERED
```

**That first assertion is deliberately wrong and you must replace it.** `Registry.get` returns a `BoundTool`, whose argument type is erased — so you cannot ask it which class produced it. Read `ancalagon/tools/registry/bound_tool.py` and `registry.py`, then assert the real thing: that invoking `delegate_solo` refuses. Drive it through `bound.invoke(json_text, ctx)` with valid arguments and assert `ok is False` and the exact error text, which `NoDelegateTo` produces. Report which form you chose.

`SOLO` is a module-level `Role` naming `delegate_solo`, `watch_file`, `idle` and `submit_answer` in its `tools`, so all three null variants are exercised. Read `tests/unit/test_tools.py` for how a `Role` is built there — `finite_budget(n, m)` from `tests/unit/conftest.py` is the helper for its budget.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/unit/test_session_for.py -v`
Expected: FAIL — `ImportError: cannot import name 'session_for'`

- [ ] **Step 3: Write it**

Add to `ancalagon/session_for.py`, below the registry builder:

```python
def session_for(
    config: Config,
    spec: TaskSpec,
    ctx: ToolContext,
    transcript: Transcript,
    run_dir: pathlib.PurePath,
    llm: LLM,
    clock: Clock,
    fs: FileSystem,
    web: WebClient,
    bus: Bus = NO_BUS,
    children: Children = NO_CHILDREN,
    letterbox: Letterbox = NO_LETTERBOX,
    meter: Meter = UNMETERED,
    depth: int = 0,
) -> Session:
    output_class = resolve_class(spec.role.answer)
    history: collections.abc.Sequence[Message] = (
        repair(load(fs, transcript.path)) if fs.exists(transcript.path) else []
    )
    return Session(
        spec=spec,
        input=ctx.input,
        messages=history,
        transcript=transcript,
        agent_id=ctx.agent_id,
        llm=llm,
        registry=build_registry(
            config,
            spec,
            run_dir,
            parent=ctx.agent_id,
            depth=depth,
            output_class=output_class,
            clock=clock,
            fs=fs,
            web=web,
            bus=bus,
        ),
        ctx=ctx,
        output_class=output_class,
        clock=clock,
        children=children,
        letterbox=letterbox,
        meter=meter,
        compact_above_tokens=config.compact_above_tokens,
        keep_recent_messages=config.keep_recent_messages,
    )
```

`agent_id` and `input` come off `ctx` rather than being taken again — they must equal what the context holds, and reading them there makes disagreement unrepresentable.

If python-fp-lint flags this for complexity, it is one expression and one conditional; report the rule rather than restructuring into something less readable.

- [ ] **Step 4: Make `worker.main` the first caller**

In `ancalagon/worker.py`, `main` keeps everything process-shaped and delegates the assembly. It already builds `bus`, `meter_store`, `log` and `spec`; it now also builds the `ToolContext` it used to hand to `Session` directly:

```python
        ctx = ToolContext(
            workspace=Workspace.from_config(config, fs),
            task_dir=task_dir,
            summary_chars=config.summary_chars,
            agent_id=agent_id,
            input=given,
        )
        session = session_for(
            config,
            spec,
            ctx,
            log,
            run_dir,
            LiteLLMClient(
                model=config.model,
                max_tokens=config.max_tokens,
                num_retries=config.num_retries,
                request_timeout_s=config.request_timeout_s,
                custom_llm_provider=config.custom_llm_provider,
            ),
            clock,
            fs,
            web,
            bus=bus,
            children=BusChildren(bus, agent_id),
            letterbox=FileLetterbox(fs, task_dir),
            meter=BusMeter(meter_store),
            depth=depth_of(bus.snapshot(), agent_id),
        )
        outcome = session.run()
```

Everything else in `main` — the outcome write, the `except`, the `finally: log.close()` — is untouched. Remove the imports `main` no longer uses; `resolve_class` may still be needed for `spec.role.input`, so check before deleting.

- [ ] **Step 5: Run the tests**

```bash
uv run python -m pytest tests/unit -v
```
Expected: PASS, including your new test. The existing worker and session tests are the net for the extraction — they assert behaviour that must not have changed.

- [ ] **Step 6: Mutation-check**

Break the code two ways and confirm a test fails each time:

1. In `session_for`, pass `children=NO_CHILDREN` unconditionally instead of the parameter — an existing test that asserts a worker sees its children must fail. Find it with `grep -rn "BusChildren\|outstanding" tests/unit`.
2. In `session_for`, pass `depth=0` unconditionally instead of the parameter — a test covering `max_depth` must fail. Find it with `grep -rn "max_depth\|depth_capped" tests/unit`.

Restore both. If either fails no test, say so plainly — it means that wiring is unasserted, which is worth knowing.

- [ ] **Step 7: Full verification**

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 8: Commit**

```bash
git add ancalagon tests
git commit -m "$(cat <<'EOF'
Assemble one agent's session in one place

A host that wanted a single agent had to copy fifty lines out of the
worker and would drift from them. session_for takes the context and the
transcript the caller owns, and defaults the rest to the null objects
that make one agent run alone.

Reading agent_id and input off the context rather than taking them again
makes them unable to disagree with it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The proof, and the documentation

**Files:**
- Create: `tests/integration/test_one_agent.py`
- Modify: `README.md` — a section on running one agent in your process
- Modify: `.talismanrc` — only if Talisman flags a changed file

**Interfaces:**
- Consumes: `session_for` from Task 2.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Write the failing test**

This is what the three specs were for: one agent, in this process, reaching nothing it was not handed. Create `tests/integration/test_one_agent.py`.

Read `ancalagon/llm/fake_llm.py` first — `FakeLLM(replies: Sequence[Reply])` — and `tests/unit/test_session_loop.py` for how a `Reply` carrying a `ToolUse` for `submit_answer` is built there. Copy that shape; do not invent one.

```python
def test_a_host_runs_one_agent_with_no_bus_and_no_subprocess(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    write_root = tmp_path / "ws"
    task_dir = write_root / "tasks" / "solo"
    fs.mkdir(pathlib.PurePath(task_dir), parents=True, exist_ok=True)
    role = Role(
        behaviour="Answer the question you are given.",
        tools=("submit_answer",),
        budget=finite_budget(2, 2),
    )
    config = Config(
        write_root=pathlib.PurePath(write_root),
        read_roots=(pathlib.PurePath(write_root),),
        model="some-provider/no-model-is-called",
        roles={"solo": role},
    )
    spec = TaskSpec(task_id="solo", role=role, goal="What is the capital of France?")
    given = FreeText(text="What is the capital of France?")
    ctx = ToolContext(
        workspace=Workspace.from_config(config, fs),
        task_dir=pathlib.PurePath(task_dir),
        summary_chars=config.summary_chars,
        agent_id=1,
        input=given,
    )
    transcript = Transcript(fs, path=pathlib.PurePath(task_dir / "transcript.jsonl"), agent_id=1)

    try:
        session = session_for(
            config,
            spec,
            ctx,
            transcript,
            pathlib.PurePath(tmp_path / "runs" / "solo"),
            FakeLLM([ANSWERED]),
            FakeClock(),
            fs,
            RealWebClient(),
        )
        produced = session.run()
    finally:
        transcript.close()

    assert isinstance(produced, Completed)
    assert produced.value.text == "Paris"
    assert list(tmp_path.rglob("bus.db")) == []
```

`ANSWERED` is a module-level `Reply` whose blocks carry a `ToolUse` calling `submit_answer` with `{"text": "Paris"}`. The role's answer contract is `FreeText` by default, so `produced.value.text` is the assertion — check `ancalagon/contracts/free_text.py` for the real field name before pinning it.

The `rglob("bus.db")` assertion is the point: no database was created anywhere, so the isolation is demonstrated rather than assumed.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/integration/test_one_agent.py -v`
Expected: FAIL. If it fails on the `FakeLLM` reply shape rather than on `session_for`, fix the reply against `test_session_loop.py` and run again — that is the test being wrong, not the code.

- [ ] **Step 3: Make it pass**

No production code should be needed. If it is, STOP and report what — a gap this test exposes is a finding about Task 2, not something to patch here.

- [ ] **Step 4: Document it**

Add a section to `README.md` after the existing "Starting a run from Python". Match that section's register — plain declarative sentences, lowercase identifiers in backticks, no marketing language. Read it before writing.

It must show the real call and state three things a host cannot guess, each of which fails late:

```markdown
## Running one agent in your process

`run` starts a whole tree. To run a single agent in your own process, with no subprocess and no
database, assemble its session directly:

```python
from ancalagon.session_for import session_for

session = session_for(config, spec, ctx, transcript, run_dir, llm, clock, fs, web)
outcome = session.run()
```

The caller owns the `ToolContext` and the `Transcript`, and closes the transcript when it is done.
The remaining collaborators default to `NO_BUS`, `NO_CHILDREN`, `NO_LETTERBOX` and `UNMETERED`,
which is what makes one agent run alone: a role naming `delegate_<role>`, `watch_file` or `idle`
gets a tool of the same name and schema whose every call refuses.

Three things fail later than you would like:

- The task directory must sit under `config.write_root`. Tool output goes through the workspace,
  so a directory outside it raises `ScopeError` at the first tool that writes, naming the tool
  rather than the wiring.
- `on_path(config.import_paths)` must run before `session_for`. Building a `delegate_<role>` tool
  imports that role's input contract, so a config built in Python whose `import_paths` are unset
  fails with a module error naming a module the host can import itself.
- `depth` defaults to `0`, which is a decision rather than a placeholder: `build_registry`
  withholds `delegate_<role>` once `depth` reaches `[limits] max_depth`.
```

Verify each claim against the source before committing it — `Workspace.resolve_write` for the
first, `ancalagon/tools/delegate/delegating.py` for the second, `build_registry` for the third.

- [ ] **Step 5: Full verification**

This is the final commit of the plan, so run everything:

```bash
uv run python -m black . && uv run pyright && uv run python -m pytest tests/unit && uv run python -m pytest tests/integration && uv run lint-imports
```

- [ ] **Step 6: Commit**

```bash
git add tests README.md .talismanrc
git commit -m "$(cat <<'EOF'
Prove one agent runs in a host process, and say what bites

A config built in Python, a scripted model, no bus and no subprocess. The
test asserts no database was created anywhere, so the isolation is shown
rather than assumed.

The README names the three things that fail later than a host would like:
the write-root scope, the import path ordering, and what a depth of zero
decides.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Notes for the executor

- The spec is `docs/superpowers/specs/2026-09-12-one-agent-in-your-process-design.md`. Read it before Task 1. It records why `ctx` and `transcript` are passed rather than built, and why `depth` and `run_dir` survive — so you do not re-propose removing them.
- **Task 1 is a pure move.** No signature changes, no new tests, no reformatting. Its whole verification is that the existing suite still passes.
- `session_for` reads `agent_id` and `input` off `ctx`. Do not add them as parameters — that is the defect the design removes.
- Do not add a `bus is NO_BUS` check anywhere. The construction-time checks inside `build_registry`'s helpers are the only ones this design has.
- If any step needs more than one corrective patch, stop and raise it rather than stacking a second fix on the first.
