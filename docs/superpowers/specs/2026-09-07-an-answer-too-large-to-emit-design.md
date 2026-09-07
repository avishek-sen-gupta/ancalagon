# An answer too large to emit

An agent whose answer contract is large cannot deliver it. `submit_answer`'s parameter schema
*is* the answer class — `SubmitAnswer.__init__` sets `self.args_model = output_class` — so the
whole answer must arrive as one tool call's arguments. When the answer needs more tokens than the
model may produce in a single completion, the reply is cut mid-string and nothing is delivered.

Measured on a run of a role whose answer is a list of records, each carrying a verbatim quotation:

```
model_calls, one agent: completion_tokens = 12000 ×7
```

Seven consecutive replies pinned to the exact `max_tokens` of the configured model. The agent had
found its answer; it could not say it. Raising `max_tokens` buys headroom until the contract grows
past the model's ceiling, which is fixed and not large.

The ceiling bites a second time. `CollectTask._read_closed` ends with
`ctx.full_result(self.name, outcome.value.model_dump_json(), ".json")`, so a parent that collects a
child pays the child's entire answer in its own context. A contract too large to emit is also too
large to collect.

## What this does not change

Nothing in the core. `AgentSpec[InT]`, `Outcome[OutT]`, `resolve_class`, `Submitted`, the hook
protocols and every existing contract are untouched. Pydantic remains the contract of record and
every value crossing a boundary is still an instance of a declared class.

What is added is a way for an agent to build its answer on disk over many turns and submit a
pointer to it, with the large structure's shape carried as a JSON Schema file rather than as a
Python class. A role opts in by naming the new tool and the new contracts; a role that does not is
unaffected.

Evidence checking, or any other property of the file, is a further hook in the chain. It is
deliberately out of scope here.

## The three pieces

### A generic JSON editor

`edit_json` mutates a JSON file in place, so a structure is assembled across many small calls
instead of one large one.

```python
class JsonOp(enum.StrEnum):
    SET = "set"
    APPEND = "append"
    REMOVE = "remove"


class EditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    op: JsonOp
    pointer: str
    value: str = ""
```

`pointer` is a JSON Pointer (RFC 6901). `value` is the JSON text to insert, empty for `REMOVE`.

The guardrails ban a shapeless `value`: no `Any`, no `object`, no `dict[str, Any]`, no hand-rolled
recursive JSON alias, and no intermediate JSON representation in Python. So the tool never builds
one. The pointer is translated to a jq path by a pure function, jq is invoked through
`run_command` with `--argjson`, and its stdout is written back through `workspace.write_text`.
`value` is text going to a subprocess that wants text — the same boundary `query_json`'s `filter`
already crosses, and the reason that tool shells out rather than parsing.

Writing through the workspace rather than redirecting in a shell keeps the write-root guard in
force and removes the temporary file. The target must already exist; `write_file` with `{}`
creates it, so no new policy is introduced.

### An input contract that names the output's schema

```python
class SchemaGuided(pydantic.BaseModel, frozen=True):
    output_schema: pathlib.PurePath
```

A project's own input contract subclasses this and adds whatever else its role needs:

```python
class RecordQuery(SchemaGuided, frozen=True):
    record: str
```

`resolve_class(role.input)` already accepts any class, so nothing in the core changes. The reason
this is a base class rather than a protocol is the reason `Cited` is: a subclass puts the error on
the broken contract, not on a distant annotation, and makes the implementations navigable from the
base.

`ToolContext` already carries the parsed input as `ctx.input`, so a hook reaches the schema path
without a new channel.

### Submitting a pointer

```python
class AnswerStatus(enum.StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class AnswerFile(pydantic.BaseModel, frozen=True):
    status: AnswerStatus
    summary: str
    path: pathlib.PurePath
```

`SubmitAnswerAsFile` declares `args_model = AnswerFile` and returns the same `Submitted` payload
`SubmitAnswer` returns, so run termination is unchanged. A role using it declares
`answer = AnswerFile` and lists `submit_answer_as_file` in its tools.

`status` and `summary` are what a parent learns from `collect_task` without opening the file: the
shape of the result and a sentence about it. They are the whole cost of collecting, in place of the
answer itself.

`Outcome` already distinguishes completed, exhausted, failed and needs-input, and `AnswerStatus` is
not a second copy of that. `Outcome` records how the *run* ended; `AnswerStatus` records what the
agent thinks of its own answer — an agent can complete its run and still know its answer is partial.

### Validating the file

```python
def adheres_to_schema(args: AnswerFile, ctx: ToolContext) -> Reviewed: ...
```

A before hook on `submit_answer_as_file`, declared per role:

```toml
[roles.record_analyst.before]
submit_answer_as_file = [
  { module = "ancalagon.tools.submit.adheres_to_schema", name = "adheres_to_schema" },
]
```

It refuses plainly when `ctx.input` is not a `SchemaGuided`, and otherwise validates the answer
file against the schema file, returning `Refused` carrying the JSON path of the first failing
element, or `Accepted(value=args)`.

Because the hook's first parameter is the tool's own args model, `accepts` gates it at build time
exactly as it gates every other hook: a wrongly shaped hook fails when the registry is built, not
mid-run.

The hook reads the file itself rather than receiving anything from the tool. The tool validates its
own arguments and nothing else: `bind_tool` parses them into an `AnswerFile`, and the tool checks
only that the path resolves inside the workspace and the file is there. It does not look at the
contents, because a tool must not depend on a hook a role may not have wired, and because the
schema describing those contents is the hook's business.

A role that wires no hook therefore submits an unchecked file. That is the correct behaviour: it is
the same latitude every other tool has, and the check is opt-in by declaration like every other
hook.

`jsonschema` is added to `dependencies`. It is already resolved in the lock as a transitive
dependency. Its `ValidationError` names the JSON path of the offending element, which is what the
model needs in order to fix the file; a schema-checking CLI would have been consistent with the
`ripgrep`/`jq` precedent but reports less and is not installed.

## Why this works

The model still emits the same total number of tokens — every record is written once, as a `value`
argument. What changes is that they are written in small pieces and land on disk as they go.

That is the property that matters. A transcript is compacted when it grows past
`compact_above_tokens`, and today everything an agent has said about its answer lives only in that
transcript. After this change the answer is on disk, and compaction costs nothing: an agent may
lose the memory of writing a record and still have the record.

## Alternatives rejected

**Raise `max_tokens`.** Buys headroom, not a solution. The model's output ceiling is fixed and a
contract can exceed it. Done anyway, as it is one line, and it does not conflict with this work.

**Split the role and fan out.** Existing infrastructure, no new code: several children each answer
a slice, the parent concatenates. It does not help. The parent must still emit the merged whole,
and `collect_task` charges it for every child's answer on the way in. A deterministic run function
could do the merge for free, but only by making every contract that might grow into a fan-out
parent, which is a large change to how roles are written for a problem that is really about one
tool's argument size.

**Tools generated from the answer contract.** For each list field on the answer class, generate an
`add_<field>` tool whose args model is the element type; each element is then validated on arrival
and no untyped JSON exists anywhere. This is the strongest version of the idea and it fits the
codebase best, but it is typed to one shape of problem and generates a tool surface per contract.
Rejected as overkill for now. It remains available later, and nothing here forecloses it.

**JSON Pointer operations implemented in Python.** The clearest errors and the simplest reading,
but it parses the file into a dict and the `value` argument has no declarable type. Both are banned
outright.

**A raw jq filter, mirroring `query_json`.** Maximum generality and no new vocabulary, but the
model must write correct jq for writes, and a mistaken path silently drops keys instead of failing.

**JSON Schema as the contract of record.** Contracts expressible without Python, and a parent could
synthesise one. It costs a second validation engine, strips the type parameter from `Outcome[OutT]`
and `AgentSpec[InT]`, and replaces typed instances with validated dicts — so a property like
`citations()` would have to be recovered by walking untyped JSON. The schema file here describes
one large structure that is never a Python value; the contracts that cross boundaries stay classes.

## Units of work

Three commits, each independently useful and separately revertible.

1. **`edit_json`.** The tool, its args model, the pointer-to-jq-path function, tests, and its row
   in the README tool table. Useful on its own to any agent that builds a file.
2. **Submitting a pointer.** `SchemaGuided`, `AnswerStatus`, `AnswerFile`, `SubmitAnswerAsFile`,
   its registration in `available_tools`, tests, README and `architecture.md`. An agent can now
   answer with a file, unvalidated.
3. **`adheres_to_schema`.** The hook, the `jsonschema` dependency, tests, and the documentation of
   the hook chain.

Each commit runs the whole verification set, integration suite included.
