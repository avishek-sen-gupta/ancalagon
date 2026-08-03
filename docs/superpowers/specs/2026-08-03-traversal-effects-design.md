# Traversal as an Effect System

**Date:** 2026-08-03
**Status:** Design approved, not yet implemented
**Supersedes:** the "Plan B" sketched in `2026-08-02-ancalagon-agent-harness-design.md` (build order, `run_harness`, codegen). The substrate described in that spec is built and stands.

## What changed, and why

The original spec framed deterministic traversal as *agent-generated code that calls agents*. Generated code would import the harness, call `delegate`, poll, and collect.

That was backwards in two ways.

**The traversal should not know what an LLM is.** A walk over a structure declares *what it needs at a point* — a summary of this node given its children's summaries. Who provides that is not the algorithm's business. Making the algorithm call an agent hardcodes a provider into something that should be provider-agnostic, and forecloses every other way of servicing the same point: a cache, a pure function, a cheaper model, a human.

**The codegen was never the valuable part.** A traversal is thirty lines and it is the part where correctness matters most — cycle condensation, ordering, dependencies. What is hard is everything *around* the touchpoint: isolation so one bad node cannot kill the walk, a budget that cannot be exceeded, retries, an auditable transcript, structured output that actually validates, somewhere to resume from. That is a runtime, and a runtime is worth building whether or not anything generates the walk.

So this spec builds the runtime as a library. Codegen becomes a caller of it, and — for the first time — a *testable* one.

## The generator contract

A traversal is a plain Python generator importing one thing from ancalagon.

```python
def traverse(graph: Graph) -> Generator[Ask, Reply, Report]:
    results: dict[str, NodeSummary] = {}
    for node in reverse_topological(condense(graph)):
        kids = [results[c] for c in graph.children(node.id)]
        answer = yield Ask("summarise_node", NodeInput(node=node, children=kids), NodeSummary)
        match answer:
            case Answered(value=summary):
                results[node.id] = summary
            case Unanswered(reason=why):
                results[node.id] = NodeSummary(text=f"unavailable: {why}")
    return Report(nodes=results)
```

```python
class Ask(pydantic.BaseModel, Generic[OutT], frozen=True):
    kind: str
    input: pydantic.BaseModel
    output: type[OutT]


class Answered(pydantic.BaseModel, Generic[OutT], frozen=True):
    value: OutT


class Unanswered(pydantic.BaseModel, frozen=True):
    reason: str
    detail: str = ""


Reply = Answered[OutT] | Unanswered
```

**`kind` names a capability, not a provider.** `"summarise_node"` may be an agent today and a lookup table tomorrow. The algorithm never learns which.

**Failure is a value, not an exception.** This matches how the codebase already works: tool failures are `ToolResult(ok=False)`, and an attempt's result is already a union. The algorithm decides whether a missing node is fatal, and the union means it cannot silently ignore the case.

**`output` is a class, not a schema.** The driver hands the worker the module defining it; the worker validates against it. A touchpoint returns a typed object.

**Yields are serviced one at a time.** The algorithm is a straight line. Independent work at the same topological level runs serially. `AskAll` returning a list is the additive change if that ever costs too much; nothing here forecloses it.

One typing risk to settle in the first task rather than assume: `Reply` is a generic alias with a free type variable, and a generator annotated `Generator[Ask, Reply, Report]` uses it unparameterised. Pyright strict may reject that. If it does, the fallback is to parameterise per traversal (`Generator[Ask, Reply[NodeSummary], Report]`) or to make `Reply` a concrete union over `pydantic.BaseModel`. Verify before writing the contracts, the way `outcome_adapter` was verified before Task 2 of the substrate.

There is deliberately **no identity or memoisation field**. Resumption bookkeeping is specific to the structure being walked and to how sophisticated the algorithm is; committing to a policy now would be guessing. The resolver is the seam where it can be added later without touching the generator contract.

## The driver

```python
class Resolver(typing.Protocol):
    def __call__(self, ask: Ask) -> Reply: ...


def drive(traversal: Generator[Ask, Reply, ResultT], resolve: Resolver) -> ResultT:
    try:
        ask = next(traversal)
        while True:
            ask = traversal.send(resolve(ask))
    except StopIteration as done:
        return done.value
```

The resolver is injected, matching how `LLM`, `Spawner` and `Clock` are already handled. Production supplies `Run.resolve`:

```python
def resolve(self, ask: Ask) -> Reply:
    spec = self.touchpoints[ask.kind]
    task_dir = self.write_task(ask, spec)
    task = self.bus.enqueue(task_dir, parent=0)
    self.supervisor.run_until_terminal(task)   # completed | crashed | timeout | abandoned
    return read_reply(task_dir, ask.output)
```

`write_task` locates the contracts module with `inspect.getfile(ask.output)` and copies it into the task directory, so a caller writes ordinary Python and never handles contract paths.

### The driver is a peer of the root agent

This is the property that makes the work small. A worker servicing a touchpoint is **the same worker as any other task** — same `Session`, same registry, same budget enforcement, same transcript, same `submit_answer`. No traversal-aware code exists anywhere on the model side, and the supervisor cannot tell the difference.

```
root agent  ──delegate──▶ writes spec.json, enqueues ──▶ supervisor ──▶ worker
drive()     ──resolve ──▶ writes spec.json, enqueues ──▶ supervisor ──▶ worker
```

`drive` is not a new layer. It is another thing that enqueues tasks and reads outcomes; one happens to be an LLM deciding what to enqueue, the other a Python generator. A touchpoint agent therefore gets `delegate` for free, because it is an ordinary agent with the ordinary registry.

### Mapping outcomes to replies

| `Outcome` | `Reply` |
|---|---|
| `Completed` | `Answered(value=…)` |
| `Exhausted` | `Answered(value=…)` — the forced final answer is still an answer |
| `Failed` | `Unanswered(reason="failed", detail=error)` |
| `TimedOut` | `Unanswered(reason="timeout")` |
| `NeedsInput` | `Unanswered(reason="needs_input", detail=question)` |

## Configuration

A new TOML section maps a capability to how it is serviced:

```toml
[touchpoints.summarise_node]
behaviour = "You summarise one node of a program graph from its body and its children's summaries."
goal = "Produce a summary of this node's effect."
turns = 6
tool_calls = 12
tools = ["read_file", "ripgrep"]
```

`tools` is optional and defaults to the run's enabled set. Prompts, budgets and tool access move without touching the algorithm, which is the payoff for the indirection. An unknown `kind` raises, naming the missing section.

## What is new

Everything else is the substrate as built.

| Module | Purpose | LoC |
|---|---|---|
| `traversal/ask.py` | `Ask` | 15 |
| `traversal/answered.py` | `Answered` | 12 |
| `traversal/unanswered.py` | `Unanswered` | 12 |
| `traversal/reply.py` | `Reply` alias | 8 |
| `traversal/resolver.py` | `Resolver` protocol | 12 |
| `traversal/drive.py` | `drive` | 20 |
| `traversal/run.py` | `Run`: owns bus, supervisor, config; `resolve` | 90 |
| `traversal/touchpoint.py` | `Touchpoint` config model | 20 |
| `config/load.py` | parse `[touchpoints.*]` | +15 |
| `supervisor/supervisor.py` | `run_until_terminal(task_id)` | +12 |

Roughly 215 lines, against a substrate of ~1250.

## Testing

Three tests, in the project's style — one per behaviour, each asserting everything that behaviour implies.

**`test_drive`** — the generator protocol end to end against a dict-backed fake resolver: values are sent back in order, an `Unanswered` reaches the algorithm, and the generator's `return` value comes out of `drive`.

**`test_resolve`** — `Run.resolve` turns an `Ask` into a task directory and row with the configured behaviour and budget, and turns each `Outcome` variant back into the right `Reply`.

**`tests/integration`** — a real walk over a small graph against a live model, gated on `ANCALAGON_LIVE=1`.

The property that matters more than the tests themselves: **a traversal's logic is unit-testable with no model, no processes and no network.**

```python
def test_walk_visits_children_before_parents():
    seen: list[str] = []
    def fake(ask: Ask) -> Reply:
        seen.append(ask.input.node.id)
        return Answered(value=NodeSummary(text="x"))
    drive(traverse(diamond_graph()), fake)
    assert seen == ["d", "b", "c", "a"]
```

## Build order

1. Contracts, `drive`, `Resolver` — testable immediately with a fake, no substrate involvement.
2. `Run.resolve`, `run_until_terminal`, `[touchpoints.*]` config.
3. One real walk, hand-written, against a live model.
4. **Only then** `run_harness`: a tool that runs an agent-authored module through the same `drive`.

Step 4 is what makes the central bet testable rather than assumed. A generated traversal and a hand-written one run through the *same* fake resolver, and the visit orders are compared: cycles condensed, children awaited, nothing skipped. Until now the only way to evaluate a generated walk was to read it.

## Known limitations

**One OS process per touchpoint.** At roughly 400ms of interpreter startup, a 500-node walk pays about three minutes of pure spawn overhead. Irrelevant against 500 multi-turn agents; noticeable if a touchpoint is a single cheap completion. The answer, if it ever bites, is an in-process resolver selected by `kind` — not to be built before a real walk is measurably slow.

**The contracts module must be self-contained.** It is copied into the task directory and imported there, so it may import `pydantic` and nothing from the caller's project. This already constrains `delegate`'s `contracts_path`; it will bite a library user sooner.

**No ceiling on a walk.** Each touchpoint is bounded; the walk is not. A generator with a bug enqueues touchpoints until it is killed. This is accepted deliberately: you wrote the walk, and its size is your problem as with any script. **The calculus changes when an agent writes the walk** — revisit at step 4, where a `max_touchpoints` cap returning `Unanswered` for every subsequent ask would bound cost while still letting the algorithm reach its `return` with partial results.

**Serial only.** Independent work at the same topological level runs one at a time. `AskAll` is the additive fix.

**Resumption stops at the driver.** The substrate resumes a *task* from its transcript, but a generator's position cannot cross a process boundary, so a crashed walk restarts from the beginning. Closing this needs the memoisation deliberately left out of the contract.
