# A bus a role can be given

## The problem

Five tools reach into the run directory and open a database nobody handed them:

```python
bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
```

`idle`, `check_task`, `collect_task`, `delegate_to` and `watch_file` all do it. The registry
that constructs them passes a `run_dir`, a `clock` and a `FileSystem`, and each tool turns those
into a bus on its own, inside `run`.

Two consequences. A tool's real dependencies are not visible at its construction site, so nothing
reading `available_tools` can tell which tools touch the bus. And an agent cannot be isolated from
the bus at all: whatever a caller does, `delegate_to` finds `run_dir/bus.db` if it exists.

That second one is what blocks running a single agent in a host process, which is where this came
from.

## What this is not

**Not the injection itself.** This spec establishes the type a bus can have and the null object
that stands in for one. Threading it through `available_tools`, `build_registry` and the five
tools is the next spec; a single in-process `Session` is the one after that.

**Not a change to what the bus does.** `LifecycleStore` keeps its behaviour, its schema and its
nine methods. It gains a declared protocol and a wrapped return type.

**Not a general repository abstraction.** The protocol is three methods because five tools use
three methods. The supervisor and the CLI commands own the lifecycle and keep a concrete
`LifecycleStore`.

## The protocol

`ancalagon/bus/bus.py`:

```python
class Bus(typing.Protocol):
    def snapshot(self) -> Snapshot: ...
    def record(self, agent: int, status: AgentStatus, source: EventSource,
               pid: int = 0, summary: str = "", seen_through: int = 0) -> None: ...
    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> Enqueued: ...
```

Three methods, not nine. Measured, not guessed — these are what the five tools call:

| tool | calls |
|---|---|
| `idle` | `snapshot` |
| `check_task` | `snapshot` |
| `collect_task` | `snapshot`, `record` |
| `delegate_to` | `snapshot`, `enqueue` |
| `watch_file` | `snapshot`, `enqueue` |

The remaining six — `claim`, `dir_of`, `attempt`, `queued_count`, `history`, `task` — are the
supervisor's and the CLI's. A protocol is what its consumers need, and no tool needs them.

`LifecycleStore` **inherits** `Bus`. Structural typing would accept it silently; inheriting puts a
mismatch on the class that broke rather than on a distant call site, which is the rule this
codebase already follows everywhere except where the contract belongs to something outside it.

## What `enqueue` returns

`enqueue` returns an agent id, so a bus that queues nothing has nothing honest to return. `0` would
tell a model "queued as agent 0", and its next `check_task` would find nothing — it would spend
turns chasing a task that never existed.

So the id gets a type, and absence gets a null object:

```python
class AgentRef(pydantic.BaseModel, frozen=True):
    id: int

class NoAgentRef(pydantic.BaseModel, frozen=True): ...

Enqueued = AgentRef | NoAgentRef
```

Shaped after `Allowance = Finite | Infinite`, which is this repo's existing answer to the same
question. `LifecycleStore.enqueue` returns `AgentRef`; `NoBus.enqueue` returns `NoAgentRef`.

Nothing raises. The type carries the absence, so the null object stays quiet the way `NO_CHILDREN`
does.

The rejected alternative was for `NoBus.enqueue` to raise. It works, but it makes a null object
throw — and it leaves the hazard invisible to the checker. With a union, **Pyright forces every
future caller to handle the no-bus case**: a new tool that enqueues cannot silently assume a bus
exists, because the union will not compile without a `match`. That is "state types for the checker,
not just for the reader" applied to the exact defect this spec exists to remove.

## Where it lands

Five callers, of which only two use the value:

| caller | change |
|---|---|
| `tools/delegate/delegate_to.py:67` | `match` — `AgentRef` proceeds, `NoAgentRef` becomes a `ctx.failure` naming the role it could not delegate to |
| `tools/watch/watch_file.py:70` | the same |
| `answer.py:70` | returns it onward; unwraps at the CLI boundary |
| `run.py:138` | discards it today, unchanged |
| `supervisor/supervisor.py:117` | discards it today, unchanged |

The two that must change are exactly the two that would break silently under a sentinel. The union
lands the burden where the hazard is.

## The null object

`ancalagon/bus/no_bus.py`:

- `snapshot()` returns an empty `Snapshot` — five empty collections. Honest: there are no other
  agents.
- `record(...)` returns `None` and does nothing. Honest: nothing is tracking this agent's
  lifecycle.
- `enqueue(...)` returns `NoAgentRef()`.

Named `NoBus` with a module constant `NO_BUS`, matching `NoChildren`/`NO_CHILDREN`,
`NoLetterbox`/`NO_LETTERBOX`, `NoRun`/`NO_RUN` and `Unmetered`/`UNMETERED`. No null object in this
codebase is called `Dummy`.

**`NoBus` has no production caller until the next spec**, which is deliberate. It is a port landing
before its consumers, the way `ancalagon/web/` did in `e7a4080` — whose commit message says
"Nothing calls it yet." Its tests are its only callers here, and the `delegate_to` and `watch_file`
tests exercise it against real tools.

## Testing

Two tests, one per behaviour, both offline.

- `enqueue` hands back an `AgentRef` carrying the agent it created, and the lifecycle behaviour
  around it is unchanged. Extend `tests/unit/test_bus.py`; do not add a file.
- `NoBus` reports an empty snapshot, records nothing, and enqueues to `NoAgentRef`.

Two further tests belong to the next spec, not this one: `delegate_to` and `watch_file` given
`NO_BUS` should each fail with an error naming what they could not queue. They cannot be written
here. `DelegateTo.__init__` takes `role_name`, `role`, `run_dir`, `parent`, `clock` and `fs` — no
bus — and builds one inside `run`. There is no seam to substitute `NO_BUS` through until the next
spec injects one. Writing those tests here would mean inventing a seam ahead of the spec that
designs it.

The consequence, stated plainly so a reviewer does not have to find it: in this spec `NoBus` is
exercised only by its own direct test. Its first real caller arrives with the injection.

## Units of work

1. `AgentRef`, `NoAgentRef`, `Enqueued`; `LifecycleStore.enqueue` returns `AgentRef`; the three
   call sites that use or propagate the value handle the union.
2. `Bus` protocol; `LifecycleStore` inherits it; `NoBus` and `NO_BUS`, with their tests.

## What follows

- **Spec B** injects a `Bus` into `available_tools`, `build_registry` and the five tools, so a tool
  no longer opens its own. That is what makes `NO_BUS` mean something.
- **Spec C** adds `session_for`, assembling a single in-process `Session` from a `Config` — the
  50 lines `worker.py` currently spells out, with the bus-bound collaborators defaulting to their
  null objects.
