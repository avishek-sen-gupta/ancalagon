# One agent in your process

## The problem

Running a single agent inside a host program means copying fifty lines out of `worker.py`.

`worker.main` resolves the answer class, loads and repairs the transcript, builds a `Registry`, and
constructs a `Session` from ten collaborators. A program that wants one agent — no subprocess, no
database, no run directory — has to reproduce all of it, and will drift from it the first time the
wiring changes.

Two earlier specs made the isolation possible: a `Bus` protocol with `NO_BUS`, and every tool
handed its bus rather than opening one. Nothing yet assembles a `Session` that uses them.

## What this is not

**Not a second way to run a tree.** `run(config, run_dir, clock, fs)` already does that, and
returns the root's `Outcome`. This is one agent, one session, in the calling process.

**Not a change to `Session`.** Its constructor, its loop and its outcomes are untouched. This
assembles it; it does not alter it.

**Not a replacement for the worker.** `worker.main` keeps every process-shaped responsibility —
reading `spec.json`, opening the bus, writing `outcome-<agent>.json`, catching what escapes. It
becomes the first caller of `session_for`, which is what stops the two assemblies drifting.

## The entry point

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

Nine required, five defaulted. The five defaults are what make one agent run alone; a worker passes
real ones.

It derives four things from what it is given, because each follows and none is a choice:

- `output_class` — `resolve_class(spec.role.answer)`
- the message history — `repair(load(fs, transcript.path))` when that file exists, else empty
- the `Registry` — `build_registry(config, spec, run_dir, ...)`
- the `Session` itself

### Why `ctx` and `transcript` are passed, not built

Both were derived in an earlier draft. Both moved out, for the same reason in different clothes.

`Transcript.__init__` opens a file handle, and `worker.py:274` closes it. A factory that opens a
handle its caller cannot close leaks one per session — invisible in a worker, which exits, and
fatal in a host that loops.

`ToolContext` is shell by this codebase's own account: one instance per worker process, advanced a
turn at a time by its output counter. A thing with that lifetime belongs to whoever owns the
process. Everything it needs — the `Workspace`, the task directory, `summary_chars`, the agent id,
the input — is known to the caller before it calls.

Passing `ctx` removed three parameters, not one. `agent_id` and `input` are read off it rather than
taken again. They must equal what the `ToolContext` holds, and today nothing enforces that —
`worker.main` merely happens to pass one variable to both. Now they cannot disagree.

### Why `spec` is a `TaskSpec` and not a role name

`spec.json` freezes the role at enqueue. Looking up `config.roles[name]` would hand a resumed worker
the *current* role rather than the frozen one, silently breaking the semantics the README documents.

### Why `depth` is a parameter

`depth_of(snapshot, agent)` raises `KeyError` on an empty snapshot, at
`ancalagon/schedule/task_of.py` via `snapshot.task_by_agent`. Reproduced. It cannot be derived when
the bus is `NO_BUS`, so it is passed, defaulting to `0`.

That default is a decision, not a placeholder. `build_registry` computes
`depth_capped = depth >= config.max_depth` and withholds `delegate_*` when it trips. At `depth=0`
with the usual `max_depth=1`, delegation is offered — correct for a root, and worth knowing for a
host that passes a real bus.

### Why `run_dir` survives

It is the one path left, and under `NO_BUS` it reaches nothing: `build_registry` passes it to the
delegate and watch construction helpers, which return `NoDelegateTo` and `NoWatchFile`, neither of
which holds it. It stays required because `build_registry` needs it whenever a real bus is present,
and a signature that hid that would stop saying delegation needs a run directory.

Passing `pathlib.PurePath("")` works today and should not be done: it resolves to `PurePath(".")`,
so `"" / "tasks" / "x"` is `tasks/x` — a relative path under whatever the process's working
directory happens to be, the moment a real bus arrives.

## What it does not create

`session_for` creates no directory and writes no file. Both paths it holds are read-only to it:
`run_dir` is passed through to `build_registry`, and the history is read from `transcript.path`.

Directories appear elsewhere, and a host should know where:

| directory | created by | when |
|---|---|---|
| the task directory | the caller's `Transcript`, which mkdirs its parent | before `session_for` is called |
| `<task_dir>/tools` | `ToolContext.write_output` | lazily, at the first tool call that writes |
| `run_dir` | nobody | never |

**One constraint that fails late.** The task directory must sit under `config.write_root`.
`ToolContext.write_output` goes through `Workspace.resolve_write`, so a task directory outside the
write root raises `ScopeError` at the first tool that writes output — not at construction, and with
a message naming the tool rather than the wiring. Reproduced. It belongs in the README.

## Thirty-one tools, then a filter

`session_for` calls `build_registry`, which calls `available_tools`, which constructs **all
thirty-one** tools before filtering to the role's list. Two consequences a host should know:

- **Constructing a delegate tool imports a module.** `delegating.py:26` calls
  `resolve_class(role.input)` inside `pydantic.create_model`. So `on_path(config.import_paths)` must
  run **before** `session_for`, not after. `worker.main` already does. A host that forgets gets a
  `ModuleNotFoundError` naming a module it can import itself — the same baffling shape the `run()`
  spec documented, and for the same reason.
- **A misspelled tool fails early.** `build_registry` raises `ValueError` naming the unknown tools
  and listing what is available, so the failure lands at `session_for` rather than mid-run.

## What `worker.main` becomes

| stays | moves into `session_for` |
|---|---|
| read the config, `on_path` | `output_class` |
| open the bus and the meter store | the message history |
| read `spec.json` → `spec`, `given` | the `Registry` |
| construct and close the `Transcript` | the `Session` |
| construct the `ToolContext` | |
| construct the `LiteLLMClient` | |
| `session.run()`, write the outcome, the `except` | |

About fifty lines become about thirty. `worker.main` passes all fourteen arguments; an embedder
passes nine.

## Testing

**Unit.** With every default taken, the registry a `session_for` builds offers `NoDelegateTo`,
`NoIdle` and `NoWatchFile` rather than their real counterparts, and the session's `children`,
`letterbox` and `meter` are the null objects. Offline; `NO_BUS` is the injected fake.

**Integration — the proof the three specs were for.** A `Config` built in Python with no TOML
anywhere, a `FakeLLM` scripted to call `submit_answer`, `NO_BUS`, and no subprocess. Assert the
returned `Outcome` carries the answer, and that no `bus.db` exists anywhere under `tmp_path`. That
last assertion is what proves the isolation rather than assuming it.

**The refactor's own net.** `worker.main`'s behaviour does not change, so the existing worker and
integration tests are the safety net for the extraction. If they pass, it is faithful.

`FakeLLM(replies)` already exists at `ancalagon/llm/fake_llm.py`, so the integration test is a real
test rather than an aspiration.

## Units of work

1. `session_for` extracted into `ancalagon/session_for.py`; `worker.main` calls it. A pure refactor,
   plus the unit test above.
2. The integration proof, and a README section documenting the entry point, the `import_paths`
   ordering, and the write-root constraint.

## What this completes

Three specs, one capability. `Bus` and `NO_BUS` gave absence a type; handing each tool its bus made
absence mean something; this assembles a `Session` that uses it. A host can now run one agent in its
own process, and that agent can reach nothing it was not handed.
