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

## The protocol

Mirrors `Tool` deliberately: same type variable, `ctx` last, and a class implementing it
**inherits** it, so a broken implementation is an error on the class rather than on a distant
list.

```python
# ancalagon/tools/registry/interceptor.py
class Interceptor(typing.Protocol[ArgsT]):
    def before(self, args: ArgsT, ctx: ToolContext) -> Reviewed[ArgsT]: ...
    def after(self, args: ArgsT, result: ToolResult, ctx: ToolContext) -> Reviewed[ToolResult]: ...
```

```python
# ancalagon/contracts/reviewed.py — discriminated on kind, as Outcome and Payload already are
Reviewed[T] = Accepted[T] | Refused

class Accepted[T: pydantic.BaseModel]:   value: T      # the same one, or a modified one
class Refused:                           reason: str   # what the agent is told, and must fix
```

`UNCHECKED` is the null object — both hooks return `Accepted`, unchanged. It is the default, so
a tool with no declared check pays one match arm.

One interceptor per tool per role. There is no chain and therefore no ordering to specify.

## Where it runs

```python
def bind_tool(tool: Tool[ArgsT], check: Interceptor[ArgsT] = UNCHECKED) -> BoundTool:
    def invoke(arguments: str, ctx: ToolContext) -> ToolResult:
        args = tool.args_model.model_validate_json(arguments)
        match check.before(args, ctx):
            case Refused(reason=reason):
                return ctx.failure(tool.name, reason)
            case Accepted(value=reviewed):
                return _after(check, reviewed, tool.run(reviewed, ctx), ctx)
```

Split as shown, because the whole thing in one function is five branches against a ceiling of
three.

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

[roles.component_analyst.checks]
submit_answer = { module = "./shapes.py", name = "CitesRealFiles" }
shell         = { module = "./shapes.py", name = "NoNetworkCalls" }
```

`Role.checks: Mapping[str, ClassRef] = {}`. It is part of the role, so it is frozen into
`spec.json` at enqueue like everything else about an agent, and a config edit mid-run cannot
redefine what a queued task will be held to.

Two validations, both at the earliest point that can see the fault:

- `check_contracts` in `cli.py` resolves every role's every check before the run starts, so a
  module that does not exist or does not parse exits 2 naming the role, the tool and the path —
  rather than crashing a worker later. This extends the loop that already does this for `input`
  and `answer`.
- `build_registry` rejects a `checks` entry naming a tool the role does not have, as it already
  rejects an unknown name in `tools`. Without this a typo silently checks nothing.

`resolve_interceptor` sits beside `resolve_class` in `contracts/resolve.py`. It cannot reuse it:
`resolve_class` requires `issubclass(resolved, pydantic.BaseModel)`, and an interceptor inherits
`Interceptor` instead.

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

**Variance is the main technical risk.** `ArgsT` appears in `before`'s return type as well as
its parameter, so `Interceptor` is invariant in it — while the class itself arrives from
configuration erased, as `type[Interceptor[BaseModel]]`. This is the same wall that stopped
`Tool[ArgsT]` living in the registry. `bind_tool` being generic is half the answer; the
narrowing at the resolution boundary is the part that needs working out, and it is where this
design is most likely to get ugly. It should be settled with a spike against Pyright strict
before the rest is built.

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

- Should the variance spike change the shape of `before`? If narrowing proves genuinely
  unworkable, the fallback is for `before` to return `Reviewed[BaseModel]` and for `bind_tool` to
  re-validate — a round trip this codebase otherwise forbids, and worth avoiding.
- Is one interceptor per tool per role enough, or does a role want to compose two? Composition is
  cheap to add later and impossible to remove, so it stays out until something needs it.
- Should `check_contracts` also verify that an interceptor's declared `ArgsT` matches the tool it
  is attached to? It would catch a real class of mistake at startup, but requires reading a type
  annotation off a resolved class, which nothing else here does.
