# Interceptors around a tool call

A role may declare, per tool, a class that sees a call before it runs and its result after, and
may accept it, modify it, or refuse it. A refusal is not a crash: the agent is told why and tries
again within its budget.

The motivating case is `submit_answer` — deterministic criteria on an answer, checked against the
input the task was given, that the agent must satisfy for the answer to be accepted. Nothing
about the mechanism is specific to that tool.

## Why `bind_tool`

`registry/bind_tool.py` is already the one place a tool call's JSON text becomes a model and
`tool.run` is called. It is also already the generic *function* that exists because
`Tool[ArgsT]` cannot be an element of a heterogeneous registry — `run` consumes its argument, so
the parameter is contravariant, and a type parameter can be scoped but not stored. An
interceptor has exactly the same shape and exactly the same problem, so it belongs in exactly
the same scope.

The alternatives were considered and are worse:

| Seam | Why not |
|---|---|
| Inside `SubmitAnswer.run` | Specific to one tool, which is not what was asked for. |
| `Session._run_tools` | Arguments are still text there; `bind_tool` parses them. Wrong layer. |
| `worker.py`, after `session.run()` | The loop is over. You can downgrade an outcome but never give the agent another turn — an audit, not a gate. It would also write `outcome-<agent>.json` twice, which is the single-write property the supervisor's `Closed`/`Lost` decision rests on. |

## The hooks

Two stateless functions, neither generic. Nothing is instantiated and nothing holds state between
calls, so an interceptor is a pure function of what it is given.

```python
# ancalagon/tools/registry/hooks.py
type Before = Callable[[BaseModel, ToolContext], Reviewed]
type After  = Callable[[BaseModel, ToolResult, ToolContext], Reviewed]
```

```python
# ancalagon/contracts/reviewed.py — discriminated on kind, as Outcome and Payload already are
Reviewed = Accepted | Refused

class Accepted:   value: pydantic.BaseModel   # the same one, or a modified one
class Refused:    reason: str                 # what the agent is told, and must fix
```

The null objects are identity functions, `unchecked_before` and `unchecked_after`.

**There is deliberately no type variable.** An earlier draft made `Before` generic in the tool's
argument type, on the theory that it would prove a hook matched the tool it was attached to. It
cannot: every hook arrives from configuration and is resolved at runtime, so the pairing is never
visible to the type checker, and the generic resolver's `cast` merely *asserted* the relationship
instead of checking it. It bought static safety only at hand-written call sites, of which this
design has none, and it cost a generic resolver, an `args_model` threaded through it, and an
invariance conflict between `Tool[ArgsT]` and `Before[ArgsT]`. Removing the type variable removes
all four, and `bind_tool` gets a real check in place of a cast.

A function cannot inherit a protocol, so these are structural — the exception this codebase
already makes for `Process`, which is the shape of `subprocess.Popen`.

One `before` and one `after` per tool per role, each independent of the other. There is no chain
and therefore no ordering to specify.

## Where it runs

```python
def bind_tool(
    tool: Tool[ArgsT], before: Before = unchecked_before, after: After = unchecked_after
) -> BoundTool:
    def invoke(arguments: str, ctx: ToolContext) -> ToolResult:
        args = tool.args_model.model_validate_json(arguments)
        match before(args, ctx):
            case Refused(reason=reason):
                return ctx.failure(tool.name, reason)
            case Accepted(value=reviewed) if isinstance(reviewed, tool.args_model):
                return _after(after, reviewed, tool.run(reviewed, ctx), ctx)
            case Accepted():
                return ctx.failure(tool.name, f"{tool.name}'s before hook returned the wrong type")
```

Split as shown, because the whole thing in one function is over the complexity ceiling of three.

`isinstance(reviewed, tool.args_model)` is doing two jobs. It narrows `reviewed` back to the
tool's argument type, so `tool.run` type-checks with no cast anywhere; and it is a genuine
runtime check, so a hook that returns some other model is reported as a refused call rather than
handed to the tool. The generic draft could only have asserted this.

An interceptor reaching the filesystem does so through `ctx.workspace`, scoped exactly as a tool
is. That is what makes "every file this answer cites exists" expressible without a new port.

`ToolContext` gains the task's input. It is already "what a tool is given to do its work", the
worker builds it where `given` is in scope, and an interceptor needs both halves to compare an
answer against what was asked. Tools ignore it.

`delegate_<role>` tools are built by `delegate_tools`, which calls `bind_tool`, so they can carry
an interceptor like anything else — a parent's delegation can be checked before a child is
enqueued.

## Configuration

```toml
[roles.component_analyst]
behaviour = "..."
input  = { module = "./shapes.py", name = "Query" }
answer = { module = "./shapes.py", name = "Component" }
tools  = ["read_file", "ripgrep", "shell"]
budget = { turns = 12, tool_calls = 30 }

[roles.component_analyst.before]
submit_answer = { module = "./checks.py", name = "cites_real_files" }

[roles.component_analyst.after]
ripgrep = { module = "./checks.py", name = "must_have_found" }
```

`Role.before: Mapping[str, FunctionRef] = {}` and `Role.after: Mapping[str, FunctionRef] = {}`.
Two flat maps rather than one map of pairs, because hooks are rarely paired: a tool usually wants
one or the other, and declaring only what you need should be the ordinary shape rather than an
omission filled by a default.

`FunctionRef` has the same two fields as `ClassRef` and is a separate type because a field should
be named after what it holds: `ClassRef` names classes, and these are functions. It is part of the role, so it is frozen into
`spec.json` at enqueue like everything else about an agent, and a config edit mid-run cannot
redefine what a queued task will be held to.

Two validations, both at the earliest point that can see the fault:

- `check_contracts` in `cli.py` resolves every role's every check before the run starts, so a
  module that does not exist or does not parse exits 2 naming the role, the tool and the path —
  rather than crashing a worker later. This extends the loop that already does this for `input`
  and `answer`.
- `build_registry` rejects a `checks` entry naming a tool the role does not have, as it already
  rejects an unknown name in `tools`. Without this a typo silently checks nothing.

Two resolvers sit beside `resolve_class` in `contracts/resolve.py`, and neither is generic:

```python
def resolve_before(ref: FunctionRef) -> Before: ...
def resolve_after(ref: FunctionRef) -> After: ...
```

**Startup validation is weaker than it would be for classes, and this is the cost of functions.**
`resolve_class` can assert `issubclass(resolved, pydantic.BaseModel)`; a function cannot be
`issubclass`-ed against anything. What is left is `callable()` and an arity check through
`inspect.signature`:

```
must_have_found must take (args, ctx)
ArgsT is not callable
```

That catches a misspelled name, a value that is not a function, and a wrong parameter count. It
does not catch a hook written against the wrong tool's arguments — that resolves cleanly, and
fails at the first call as an ordinary refused result, either from the hook's own `isinstance` or
from `bind_tool`'s narrowing. Each resolver ends in one `typing.cast`, because `getattr` yields
something unknown and nothing else can bridge that.

A hook may annotate its argument concretely — `def cites_real_files(answer: Component, ctx)` —
even though `Before` is declared over `BaseModel`. Nothing verifies the pairing either way, so
the concrete annotation costs nothing and reads better; `bind_tool` is what actually checks the
type at the boundary.

## What a refusal does

Nothing new. `ctx.failure` produces a failed `ToolResult`; `_outcome_of_use` matches no payload
type and returns `PENDING`; `_evaluate_turn` returns `PENDING`; `run()` loops. The agent's next
turn contains the refusal as a tool result and it tries again. This is the same path a malformed
argument has taken since `bind_tool` became the single validation site.

The one place the session must change is the **forced final turn**. Today, when every tool call
on that turn yields `PENDING`, `_evaluate_turn` falls through to `_finish_from_text`, which
validates the reply's *text* blocks. On a forced tool call there are none, so `json_payload("")`
is `""`, validating it raises, and the attempt ends:

```json
{"kind": "failed", "error": "final answer did not validate: ...", "summary": "<the arguments>"}
```

The schema was fine; the criteria were not. A parent reading that gets the wrong diagnosis. The
reason exists — it is `ToolResult.error` on the refused call — and `_handle_uses` discards it,
mapping results to outcomes and dropping the results.

**Decision: a refusal on the forced final turn ends the attempt as `Failed`, naming the
refusal.** A check is a hard gate; an answer that never satisfied it is not an answer, and the
parent should be told accurately and decide whether to re-delegate.

```json
{"kind": "failed",
 "error": "submit_answer refused: cited file src/foo.py does not exist",
 "summary": "{\"summary\": \"...\", \"files\": [...]}",
 "spent": {"turns": 14, "tool_calls": 35}}
```

So `_handle_uses` must carry the refusal reason forward rather than discard it. That is the only
change to `session.py` this design requires.

## Known limits, stated rather than glossed

**`after` cannot undo a side effect.** It runs after `tool.run`, so refusing after `write_file`,
`edit_file`, `delete_file` or `shell` leaves the mutation in place. Prevention belongs in
`before`. This does *not* apply to `submit_answer`, whose only effect is writing a stub file:
`after` runs before `_outcome_of_use` builds the outcome, which is long before `worker.py`
writes it, so an answer can be refused or modified with nothing to reverse.

**A refused `submit_answer` leaves an orphan tool output.** `SubmitAnswer.run` calls
`ctx.write_output` before returning, so a refusal in `after` leaves a
`tools/NNNN-submit_answer.txt` containing `"answer accepted"` and advances the counter. Harmless
— tool outputs are an append-only log — but it will look odd to a reader.

**A refused call still spends its budget.** `_run_tools` charges `tool.cost` before invoking.
This is existing behaviour for validation failures and is left unchanged; it is noted because it
means a role with tight `tool_calls` and a strict check can exhaust itself on retries.

**A modification is invisible at runtime.** `Submitted.text_for_model()` returns `"answer
accepted"` whatever happened, and the session ends immediately after, so no one is told the
answer was rewritten. The information is not lost — the transcript's `ToolUse` block holds what
the agent submitted and `outcome-<agent>.json` holds what was accepted, so a diff shows it — but
nothing states it. This is left as is, with a caveat: silently rewriting an answer sits badly
with a harness whose value is auditability, and a check that modifies should be a considered
choice rather than a convenience.

## Scope

In: the protocol, `Reviewed`, the null object, `bind_tool`, `Role.checks`, `resolve_interceptor`,
the two startup validations, the task input on `ToolContext`, and the `_handle_uses` change that
makes a final-turn refusal report accurately.

Out: chained interceptors, interceptors declared anywhere but a role, interceptors that can see
the transcript or the bus, retry policy of any kind, and any change to what a modification
records.

## Open questions

- Is one interceptor per tool per role enough, or does a role want to compose two? Composition is
  cheap to add later and impossible to remove, so it stays out until something needs it.
- Should `check_contracts` verify that a hook's declared parameter type matches the tool it is
  attached to? It is the one mistake the arity check cannot catch, and `inspect.signature` already
  has the annotation in hand — but reading types off a resolved function is something nothing else
  here does, and a wrong-typed hook already fails safely, as a refused call rather than a bad
  one.
