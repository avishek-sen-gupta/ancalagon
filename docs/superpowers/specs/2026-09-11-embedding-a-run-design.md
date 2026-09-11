# Embedding a run

## The problem

There is no formal way to start Ancalagon from inside a Python program. `cli.main(config_path,
run_dir)` can be imported and called, but it is shaped for a process rather than a caller: it
configures logging, writes the outcome JSON to stdout, and returns an exit code. A host that wants
the answer gets a side effect and an integer.

Underneath that, a second problem. `worker.py` calls `load_config(config_path, fs)`, so every
worker process parses TOML. A worker runs one agent. Config *formats* have no business in it.

## The rule this establishes

One layer at the top converts a representation into a `Config`. Everything below it is handed the
`Config` and knows nothing about where it came from.

```
TOML file ─┐
JSON file ─┼─→ Config ──→ run(config, run_dir) ──→ supervisor ──→ worker
host code ─┘   (the conversion layer)                             (takes Config)
```

`load.py` stays exactly what it is — the TOML boundary — and becomes one of several doors to a
`Config` rather than the only one. A host that builds roles in Python needs no TOML at all.

## What this is not

**Not a new config format.** TOML remains the language humans author. A role's `behaviour` is a
prompt: `blackboard.toml`'s analyst is an 18-line prose block, and the three shipped configs carry
six comments explaining why a role exists. JSON has neither multi-line strings nor comments. As
JSON that behaviour is a single 1268-character line, unreviewable in a diff. JSON is the resolved
machine form, not the authoring form.

**Not a plugin system.** A host supplies a `Config` and gets an `Outcome`. It does not get hooks
into the supervisor, the session loop, or a running agent.

**Not a change to what a role is.** Roles, contracts, budgets and hooks are unchanged. Only the
route by which a `Config` reaches the code that uses it changes.

## The entry point

A new module `ancalagon/run.py`, between `cli` and `supervisor` in the layer contract:

```python
def run(config: Config, run_dir: PurePath, clock: Clock, fs: FileSystem) -> Outcome[BaseModel]
```

It validates the config, materialises it, enqueues the root task, supervises to idle, and returns
the root's outcome parsed against the answer class its role declared. A typed value: not a printed
string, not an exit code.

`Outcome` is a union alias (`Completed | Exhausted | NeedsInput | Failed | Idling`), read through
`pydantic.TypeAdapter(Outcome[X]).validate_json` as `deterministic/run.py` already does. A host
matches on it the way a deterministic run function does.

Three things move down out of `cli.py` into `run.py`, because none of them are CLI work:

- `check_contracts` — config validation. This is the one with churn: about twelve test call sites
  import it from `ancalagon.cli`.
- `sandbox_of`
- `root_spec`

`cli.py` keeps argument parsing, the stdout write, and the exit code — the process-shaped parts an
embedder does not want. The CLI becomes one caller of the embedding surface rather than a parallel
route to the same machinery.

`init` keeps taking a config, because it needs `write_root` to allocate a directory.
Materialisation happens in `run`, not `init`, so an embedded host never needs an `init` step it
cannot satisfy.

## Crossing the process boundary

A worker is a separate OS process. It cannot be handed a Python object. The `Config` crosses once,
as text, and is parsed the instant it arrives — the codebase's own one-hop rule.

`run()` writes `run_dir/config.json` before enqueueing the root task. `SubprocessSpawner` points
`--config` at that file. Both worker entry points — `ancalagon/worker.py` and
`ancalagon/deterministic/run.py` — replace their `load_config(config_path, fs)` call with:

```python
config = Config.model_validate_json(fs.read_text(config_path))
```

TOML parsing, the `Raw*` models, relative-path resolution and the `[web]` table stop existing below
the supervisor.

`run()` writes `config.json` on every invocation, so a resumed run overwrites it. Existing run
directories need no migration.

Passing the config on stdin was rejected. A re-spawned worker needs the config again, and the run
directory is the durable record of a run.

## The import anchor

`load_config` calls `importable(base)` (`load.py:109`), appending the config file's own directory
to `sys.path`. That global mutation is the only reason `shapekit.shapes` and `pongkit.checks`
resolve. A `Config` built in memory has no directory, and a worker that no longer knows which file
it came from cannot reproduce the anchor.

So the anchor becomes data the config carries:

```python
class Config(pydantic.BaseModel, frozen=True):
    import_paths: tuple[pathlib.PurePath, ...] = ()
```

`load_config` sets it to `(base,)`, preserving today's behaviour exactly. A host building a
`Config` in Python sets it to wherever its own packages live. Applying it — putting each path on
`sys.path` before any `resolve_class` call — becomes an explicit step at worker startup rather than
a side effect of parsing.

This is the piece that makes the whole design possible. Without it, an in-memory `Config` cannot
name a contract class.

## The behaviour that changes

Today every worker re-reads the source config, so editing `model` or `agent_timeout_s` mid-flight
reaches the next worker spawned. After this, the config is fixed for the duration of one `run()`
invocation, and a resumed run picks up edits at the next invocation.

The operational lever survives at coarser grain: it now takes a stop and a restart rather than
taking effect silently mid-run. `README.md` documents the current partial-freeze behaviour, so that
paragraph changes with the code.

A run directory also becomes self-describing as a consequence. Today `spec.json` freezes each role,
but the model, the limits, the sandbox strategy and the egress list are recorded nowhere — a
finished run cannot say what it was allowed to reach. After this, `config.json` says.

## Testing

`FakeFileSystem` and `FakeClock` already exist, so every test stays offline.

Five unit tests, one per behaviour:

- `load_config` sets `import_paths` to the config file's own directory, and a `Config` built in
  Python carries whatever it was given
- `run()` writes a `config.json` that round-trips: `Config.model_validate_json` of it equals the
  `Config` it was given
- a worker started against a materialised `config.json` builds the same registry as one started
  against the TOML it came from
- `run()` returns the root's outcome as a typed value, not a string
- `check_contracts` still refuses the roles it refused before, imported from its new home

One integration test: a delegating run started from an in-memory `Config` with no TOML file
anywhere, asserting the child agent resolved its contract class through `import_paths`. This is the
case that fails today and the reason for the whole design.

## Units of work

1. `Config.import_paths` — field, `load_config` sets it, `importable()` stops being a parse side
   effect and becomes an explicit startup step
2. `ancalagon/run.py` — the entry point; `check_contracts`, `sandbox_of` and `root_spec` move down
   from `cli.py`; `cli.main` becomes a caller
3. Materialisation — `run()` writes `config.json`, the spawner points at it, both worker entry
   points swap `load_config` for `model_validate_json`
4. Docs — `README.md`'s partial-freeze paragraph, `docs/architecture.md`, and a note on the
   embedding surface
