# Deterministic agents

A role may name a Python function instead of describing behaviour to a model. The supervisor
spawns a process for it, that process reads `spec.json` and writes `outcome-<agent>.json`, and
the parent that delegated to it cannot tell the difference. The function itself contains no
harness vocabulary: it takes its input contract and a context, and returns its answer contract.

`ancalagon/watch/watch.py` is this, written once by hand. Everything in it except `watch_for` is
boilerplate, and `WatchSpawner` is `SubprocessSpawner` with one string changed. This design turns
that one instance into the general case and deletes both.

## The run function

```python
# the whole of a deterministic agent
def watch_for(request: WatchRequest, ctx: RunContext) -> Watched:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    return Watched(path=request.path, at=ctx.fs.changed_at(watched))
```

Arity is fixed at two, both positional. The first parameter's annotation is the role's input
contract; the return annotation is its answer contract. Both must be `pydantic.BaseModel`
subclasses, and a function that does not say so is refused at config load.

```python
# ancalagon/deterministic/run_context.py
@dataclasses.dataclass(frozen=True)
class RunContext:
    fs: FileSystem
    clock: Clock
    task_dir: pathlib.PurePath
    run_dir: pathlib.PurePath
```

A frozen dataclass, not a model: `FileSystem` and `Clock` are protocols, and a Pydantic model
holding them would need `arbitrary_types_allowed`. Nothing here crosses a wire.

`fs` and `clock` are the ports `watch_for` already takes. `task_dir` and `run_dir` are there
because a deterministic step that produces artifacts needs somewhere to put them, and because a
function reaching for a path any other way would be reaching around the `FileSystem` port.

The function returns the answer contract alone — no `Completed`, no `Budget`. The runner wraps:

```python
Completed(value=produced, summary=produced.model_dump_json()[:SUMMARY_CHARS], spent=NOTHING)
```

This loses the sentence `watch.py` writes today (`/path/board.md changed at 175…`) in favour of
truncated JSON, which is what `check_task` and `collect_task` show the parent. For the small
answer models these contracts are, that reads about as well, and it is the price of a run
function with nothing of the harness in it.

## Refs become dotted names

`ClassRef.module` and `FunctionRef.module` hold a file path today, because the hooks and
contracts that configs name are per-run files sitting next to the TOML — `./checks.py`,
`./pong_checks.py` — which are not on any import path. `resolve.module_of` loads them with
`spec_from_file_location`, keyed and cached by path.

Deriving a `ClassRef` from an introspected class under that scheme means going back out through
`sys.modules[cls.__module__].__file__`, which is a round trip through the import system to
recover something it already knows. Both refs become dotted instead:

```python
class ClassRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
    name: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
```

`FunctionRef` gains the same pattern on `module`; it has none on either field today.
`resolve.module_of` and `_load_fresh` collapse into `importlib.import_module`, and the
`functools.cache` goes with them, because `sys.modules` is already that cache. A config still
naming `./checks.py` now fails at load with a message about the pattern, rather than at first
use.

For a config's own files to be importable, `load_config` inserts the config file's directory on
`sys.path` before building the `Config`. It already computes that directory as `base`. Every
process that resolves a ref — the CLI, each worker, each deterministic child — reaches it by
loading the config first, so one insertion covers all of them; the alternative was the same line
repeated in three entry points and forgotten in the fourth.

This puts a mutation of interpreter state inside `load_config`. It is defensible where it sits —
`load.py` already takes a `FileSystem` and reads the file, so it is a loader, not domain — but it
is the one place in this design where a function does something its name does not say.

The per-run files move into packages of their own rather than staying loose modules, so that a
run directory holding `checks.py` cannot shadow something on the path: `pong_checks.py` becomes
`pongkit/checks.py`, named `pongkit.checks`. The package must not take the name of the run's
write root, which is already a directory beside it.

## Contracts derived, not declared

`config/load.py:_role` is where a `RawRole` becomes a `Role`. A role that declares `run` has its
`input` and `answer` filled in from the run function's signature there:

```toml
[roles.watcher]
behaviour = "Wait for the blackboard to change."
run = { module = "ancalagon.watch.watch_for", name = "watch_for" }
tools = []
budget = { turns = 0, tool_calls = 0 }
```

No `input`, no `answer`. Declaring either alongside `run` is an error, not an override — two
statements of one contract is the thing this removes.

The introspection is `accepts` in `tools/registry/accepts.py`, which already reads
`typing.get_type_hints`, checks arity and positionality, and requires the first parameter to be a
model class, returning a fault string naming the module and function. It grows a check on the
return annotation with the same treatment, and `resolve_run` joins `resolve_before` and
`resolve_after` beside it.

Deriving in `delegate_tools` was considered and rejected. It runs inside a worker process and
fixes only the tool schema the caller sees; `DelegateTo` still writes the config's `Role` into
`spec.json`, and `collect_task` in the parent and the runner in the child both read the contracts
back off it. The derivation would have to happen three times, or the three would disagree.

`Role` therefore keeps `input` and `answer` exactly as they are, and every existing consumer —
`DelegateTo.args_model`, `worker.py`, `collect_task` — is untouched.

## The runner and the spawner

```python
# ancalagon/deterministic/run.py — the whole template
def main(run_dir, task_dir, agent_id, config_path) -> int:
    fs = RealFileSystem()
    outcome_path = task_dir / f"outcome-{agent_id}.json"
    try:
        fs.write_text(outcome_path, _completed(run_dir, task_dir, config_path, fs).model_dump_json())
        return 0
    except Exception as exc:
        failure = Failed(error=traceback.format_exc(), summary=str(exc)[:SUMMARY_CHARS], spent=NOTHING)
        fs.write_text(outcome_path, failure.model_dump_json())
        return 1
```

`_completed` loads the config, reads `spec.json` as `TaskSpec` for the role, resolves the role's
`run` and `input`, validates `AgentSpec[input_class]` from the same text, calls the function with
a `RunContext`, and wraps what comes back. This is `watch.main` with the function no longer
hardcoded and the config now read — `watch.py` ignores its `--config` today.

`ModuleSpawner` replaces `WatchSpawner`: `SubprocessSpawner` parameterised by the module it runs,
with `ancalagon.worker` as the default. `WatchSpawner` and `SubprocessSpawner` differ only in
that string.

`SpawnByInput` becomes `SpawnByRun`, and the question it asks changes from what the input
contract is called to whether the role declares a run function:

```python
def spawn(self, task_dir, agent_id) -> Process:
    spec = TaskSpec.model_validate_json(self.fs.read_text(task_dir / "spec.json"))
    return (self.deterministic if spec.role.run else self.default).spawn(task_dir, agent_id)
```

The `by_input={"WatchRequest": watching}` map in `cli.py` and in two tests goes away with it. It
was a stand-in for this question: a role served by a process rather than a model was recognised
by the name of the contract it happened to take.

`ancalagon.deterministic` is a new top-level package, so it joins `ancalagon.watch` in the
`source_modules` of the two forbidden-import contracts in `pyproject.toml`: SQL stays in the
adapters, and `os` is reached only by the adapters that own it.

## Delegation is unchanged

`delegate_tools` builds one `delegate_<role>` tool per declared role, with `args_model.input`
typed as `resolve_class(role.input)`. A deterministic role has an `input` like any other, so it
gets its tool with its contract in the schema the model sees, and `role.behaviour` still supplies
the tool's description — it is what the caller is told the step does, even though no model reads
it. `DelegateTo.run` writes `spec.json` and enqueues; `check_task` and `collect_task` read
`outcome-<agent>.json` against `resolve_class(spec.role.answer)`. None of this changes, which is
the point: `Completed[Watched]` is `Completed[Watched]` whether a model or a `while` loop
produced it.

## What is deleted

- `ancalagon/watch/watch.py`, replaced by `watch_for` alone in `ancalagon/watch/watch_for.py`
- `ancalagon/supervisor/watch_spawner.py`
- `ancalagon/supervisor/spawn_by_input.py`
- `resolve._load_fresh` and `resolve.module_of`
- the `input`/`answer` lines in `wake.toml` and `blackboard.toml`

## Units

Each is independently committable and separately revertible.

1. **Dotted refs.** `ClassRef` and `FunctionRef` gain patterns; `resolve_class` uses
   `importlib.import_module`; `load_config` inserts the config's directory on `sys.path`;
   `_class_ref` and `_hooks` stop resolving paths; the loose per-run modules become packages and
   the ten `module = ` lines across the example configs are rewritten. Everything still works
   with `watch.py` as it is.
2. **`Role.run` and derivation.** `RawRole.run`, `Role.run`, `accepts` extended to the return
   annotation, `resolve_run`, `_role` filling `input`/`answer` from the signature and refusing a
   role that declares both. Nothing consumes `run` yet.
3. **The runner.** `RunContext`, `ancalagon/deterministic/run.py`, `ModuleSpawner`. `watch.py`
   still exists and still runs.
4. **Collapse `watch`.** `watch_for` moves to its own module with the `RunContext` signature;
   `SpawnByRun` replaces `SpawnByInput`; `cli._spawner` is rewritten; `wake.toml` and
   `blackboard.toml` declare `run`; `watch.py` and `watch_spawner.py` are deleted. The blackboard
   integration test proves the collapse end to end.

## Testing

`tests/unit/test_watch.py` and `tests/integration/test_blackboard.py` already cover the behaviour
this generalises, and both must keep passing through unit 4 with only their wiring changed. The
new tests are one per behaviour:

- **Dotted resolution.** A config naming a package beside it resolves its hook and its contract;
  a config naming a path fails at load with a message about the pattern.
- **Derivation.** A role naming a run function gets `input` and `answer` matching the signature;
  a function with the wrong arity, an unannotated parameter, a non-model annotation, or a missing
  return annotation is refused with the module and function in the message; a role declaring both
  `run` and `answer` is refused.
- **The runner.** A run function returning a model produces `Completed` with the wrapped value
  and a JSON summary; one that raises produces `Failed` carrying the traceback, and the process
  exits 1.
- **Dispatch.** `SpawnByRun` sends a task whose role declares `run` to the deterministic spawner
  and every other task to the default.

Each new test is mutation-checked before being trusted: break the code it covers in the two most
obvious ways and confirm it fails.
