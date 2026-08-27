# A run function chooses its own outcome

A deterministic agent ends the way a session ends. Today its `run` function returns its answer
contract and `deterministic/run.py` wraps that in `Completed`, so the only ending it can reach is
success. A session can also idle, ask its parent a question, or fail — and until a run function
can idle, no deterministic agent can spawn a child and be woken when that child settles, because
the supervisor's wake path keys on an `Idling` outcome.

The fix is to stop wrapping. `run` returns `Outcome[OutT]` and picks the ending itself.

## Why idling is what forces this

`Supervisor._wake_idling` calls `wakeable(snapshot)`, which is `has_news` per task:

```python
idled = [e.id for e in snapshot.events[parent] if e.status is AgentStatus.IDLING]
if not idled:
    return False
```

No `Idling` event, no wake. When there is one and a child settles after it, the supervisor
**enqueues a new agent against the same task directory** — so a woken run function is *called
again*, with the same `task_dir` and a new agent id, not resumed. Nothing else in the harness
grants a second call.

`deterministic/run.py:_completed` can only ever produce `Completed`, so a deterministic parent
runs exactly once. That is the whole of the limitation.

## The alias

`contracts/outcome.py` holds a concrete union today, and `outcome_adapter` builds the
parameterised one at runtime from a class it is handed. Those are the same type said twice. It
becomes one generic alias:

```python
type Outcome[OutT: pydantic.BaseModel] = (
    Completed[OutT] | Exhausted[OutT] | NeedsInput | Failed | Idling
)
```

`Exhausted` stays in the union although a deterministic agent has no budget to exhaust. The point
of the change is that a run function ends the way a session ends; carving the union down per
producer would reintroduce the difference this removes.

Two mechanics were verified before committing to this, not assumed:

- `typing.get_type_hints` on `def f(...) -> Outcome[Watched]` yields a `GenericAlias` whose
  `typing.get_origin` is `Outcome` and whose `typing.get_args` is `(Watched,)`. Contract
  derivation still reads the answer class straight out of the signature.
- `pydantic.TypeAdapter(Outcome[NodeSummary])` builds, round-trips `Completed`, `Idling` and
  `Failed`, and rejects a `value` of the wrong shape.

`outcome_adapter` is deleted. Its body becomes `pydantic.TypeAdapter(Outcome[cls])`, which only
restates its argument, and it has one caller. `collect_task` constructs the adapter at the
boundary where it parses, which is where the serialisation rules say it belongs.

Bare `Outcome` annotations become `Outcome[pydantic.BaseModel]` — eight in `session.py`, one in
`collect_task.py`, one in `tests/unit/test_escalation.py`. Not a style choice: Pyright strict's
`reportMissingTypeArgument` and the no-bare-generics guardrail both require the parameter, and
`Outcome[pydantic.BaseModel]` is exactly what the concrete union said.

## What a run function looks like

```python
def watch_for(request: WatchRequest, ctx: RunContext) -> Outcome[Watched]:
    watched = pathlib.PurePath(request.path)
    while ctx.fs.changed_at(watched) <= request.since:
        ctx.clock.sleep(request.poll_s)
    at = ctx.fs.changed_at(watched)
    return Completed(
        value=Watched(path=request.path, at=at),
        summary=f"{request.path} changed at {at}",
        spent=NOTHING,
    )
```

The summary is the function's own sentence again. The previous design traded it for a truncated
`model_dump_json`, on the argument that a run function should contain no harness vocabulary. That
argument loses once the function must choose between endings: choosing is the harness vocabulary,
and having chosen, writing the sentence costs nothing.

`spent=NOTHING` on every return is the price. A deterministic agent's spend is always zero and it
must now say so. That is the same field a session fills with a real number, which is the parity
being bought.

## Deriving the answer contract

`run_contracts` reads the first parameter's annotation with `declared`, which requires a
`pydantic.BaseModel` subclass. `Outcome[Watched]` is not one, so the return needs its own reader
rather than a reuse of `declared`:

```python
# ancalagon/contracts/outcome_arg.py
def outcome_arg(found: collections.abc.Callable[..., object]) -> Declared:
    try:
        hints = typing.get_type_hints(found)
    except NameError as exc:
        return None, f"has an annotation that cannot be resolved: {exc}"
    if "return" not in hints:
        return None, "does not annotate its return"
    ret = hints["return"]
    if typing.get_origin(ret) is not Outcome:
        return None, f"annotates return as {ret}, which is not Outcome[...]"
    match typing.get_args(ret):
        case (arg,) if isinstance(arg, type) and issubclass(arg, pydantic.BaseModel):
            return arg, ""
        case args:
            return None, f"parameterises Outcome with {args}, which is not one model class"
```

It returns the same `Declared` pair as `declared`, so `run_contracts._must` consumes it
unchanged, and it repeats `annotation_fault`'s `try/except NameError` for the same reason — an
unresolvable annotation is reported with the module and function name, as it is for a hook. The
duplication is two lines and the alternative is a parameter that means "which reader to use",
which is worse.

A run function returning a bare model class is now refused at config load, naming what it should
have said. That is a breaking change to a contract exactly one function in the repository uses.

## The runner stops wrapping

```python
def _outcome(run_dir, task_dir, agent_id, config_path, fs) -> Outcome[pydantic.BaseModel]:
    load_config(config_path, fs)
    spec_text = fs.read_text(task_dir / "spec.json")
    spec = TaskSpec.model_validate_json(spec_text)
    given = AgentSpec[resolve_class(spec.role.input)].model_validate_json(spec_text).input
    ctx = RunContext(
        fs=fs, clock=SystemClock(), task_dir=task_dir, run_dir=run_dir, agent_id=agent_id
    )
    return resolve_run(spec.role.run)(given, ctx)
```

`main` writes what it is handed. The single `try/except Exception` stays and still turns an
escaped exception into `Failed` — a run function may now also *return* `Failed` deliberately, and
the two are indistinguishable on disk, which is correct: the supervisor reads a kind and a
summary either way.

`Run`'s protocol return type becomes `Outcome[pydantic.BaseModel]`.

## `RunContext` gains the agent id

```python
@dataclasses.dataclass(frozen=True)
class RunContext:
    fs: FileSystem
    clock: Clock
    task_dir: pathlib.PurePath
    run_dir: pathlib.PurePath
    agent_id: int
```

A run function that idles has, by definition, something to be woken by, and enqueuing a child
means writing `spec.json` and calling `bus.enqueue(task_dir, parent_agent=<its own agent>)`.
`has_news` matches a child to its parent through `child.parent_agent`, so without the agent id a
run function can create a task but never one that will wake it. `main` already has the value and
passes it nowhere.

This is the whole of what a run function needs to spawn: it has `fs` and `run_dir` for the
`spec.json` write and the bus, and it can build a child `Role` in Python the way
`tests/integration/test_blackboard.py` does.

## What this does not do

No convenience for spawning. A run function that wants a child writes the spec and enqueues it
itself, with the same two calls `DelegateTo.run` makes. Whether that repetition earns a helper is
a question for the second run function that needs it, not this change.

No check that a returned `Idling` is honest. A run function may idle with no children, and the
supervisor will never wake it — the task simply stalls until the run ends. `Idle`, the tool,
refuses that case by consulting `live_children`; the equivalent guard for run functions is
deferred until something needs it.

## Units

1. **The alias.** `Outcome` becomes generic; `outcome_adapter` is deleted; `collect_task` builds
   its own `TypeAdapter`; the ten bare annotations gain their parameter. No behaviour changes —
   same union, same wire format, same validation — and the unit suite proves it.
2. **The run contract.** `outcome_arg`, `run_contracts` requiring `Outcome[X]`, `Run`'s protocol
   return type, the runner writing what it is handed, `watch_for` rewritten.
3. **The agent id.** `RunContext` gains the field and `main` passes it.

Unit 1 stands alone and is worth committing before either of the others. Units 2 and 3 are
independent of each other.

## Testing

- **Unit 1:** `tests/unit/test_contracts.py`'s adapter test, rewritten against
  `pydantic.TypeAdapter(Outcome[NodeSummary])`, asserting the same round trips it asserts now.
  Nothing else in the suite should need to change; anything that does is a behaviour change that
  was not supposed to happen.
- **Unit 2:** a run function returning `Outcome[Produced]` derives `answer=Produced`; one
  returning a bare `Produced` is refused with a message naming `Outcome[...]`; one parameterising
  `Outcome` with a non-model is refused; the runner writes an `Idling` a function returned, with
  the function's own summary, and still writes `Failed` for one that raises.
- **Unit 3:** the runner passes the agent id it was invoked with, asserted through a run function
  that returns it in its answer.
- `tests/integration/test_blackboard.py` must keep passing throughout: it is the end-to-end proof
  that a real supervisor, a real subprocess and a real run function still agree.
