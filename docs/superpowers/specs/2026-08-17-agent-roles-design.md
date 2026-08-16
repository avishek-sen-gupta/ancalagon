# Agent roles — design

## Why

Today a parent agent decides everything about its children: what they are told, what shape
they are given, what shape they must answer in, and how much budget they get. It authors the
contracts at runtime by writing Python into the workspace and naming it in the `delegate`
call. Nothing checks any of it.

Run `ws/runs/r_0004` is what that costs. The root's first three `delegate` calls all failed
identically — it sent `input_json: "{}"` because nothing told it the default contract's wire
form — then it gave all three children 8 turns, and all three hit the cap and were forced to
answer mid-investigation. The one thing the harness could have known in advance, it left to
the model, three times in a row.

Contracts are also the thing users have firmest opinions about. A person analysing a codebase
knows they want `{component: {name, description, input, output, invariants}}` before the run
starts. Making a model invent that at runtime is machinery serving nobody.

A **role** is a name bound to everything about an agent except its task: behaviour, input
contract, answer contract, tools, budget. Roles are declared in configuration. A parent picks
one and supplies a payload. It cannot author, alter or exceed anything else.

## What was chosen, and what was rejected

Three levels of programmability were considered.

**Level 1 — the current mode.** Contracts authored by the parent at runtime. Rejected, and
removed rather than kept alongside. It is a large amount of machinery whose correctness
depends entirely on the model, for an outcome most users would rather state up front.

**Level 2 — roles (this design).** Contracts declared in configuration; parents choose among
declared roles. Chosen.

**Level 3 — a deterministic program.** A human-authored program invoking Ancalagon with
typed calls, the task graph expressed as ordinary control flow rather than as graph
construction. This is the unbuilt half of the project's original thesis, and roles are its
prerequisite: they are the typed callables such a program composes. Out of scope here.

## What a role is

```toml
[roles.component_analyst]
behaviour = "Read before concluding. Cite the files you read."
input  = { module = "./shapes.py", name = "ComponentQuery" }
answer = { module = "./shapes.py", name = "Component" }
tools  = ["read_file", "ripgrep", "find_symbol"]
budget = { turns = 12, tool_calls = 30 }
```

Nothing is built in. A run that wants a freestyling agent declares one, and a run that does
not want prose anywhere simply never declares it:

```toml
[roles.scout]
behaviour = "Investigate and report what you found."
tools  = ["read_file", "ripgrep", "list_dir"]
budget = { turns = 10, tool_calls = 25 }
```

An omitted `input` or `answer` means `FreeText`, which is how a role opts into prose without
naming a path inside the installed package. So prose is still a contract, and declaring a
role is still the only way to get an agent.

`tools` is per-role, replacing the global `[tools] enabled`. It names tools, and the delegate
tools are named `delegate_<role>`, so `tools = ["read_file", "delegate_scout"]` is a role that
may spawn scouts and nothing else. A role naming no `delegate_*` tool cannot spawn at all,
which is how a program pins a subtree to depth 1 without a new mechanism.

`budget` is authoritative and fixed. A parent does not choose it and cannot be wrong about
it. This means total work is no longer bounded by the root's budget: a parent with 8 turns
may spawn ten children of a 20-turn role. It is bounded instead by the role graph and
`max_depth`, and that is the config author's business. `Allowance`, `WithinParent` and
`AsAsked` are deleted.

## What `delegate` becomes

Roles are known at worker startup, before the tool schema is built. So there is one delegate
tool **per role**, its argument model built then with `create_model`, exactly as
`AgentSpec[InT]` and `Completed[OutT]` are built today. What a spawning role is shown is two
more entries in the tool list it already receives, whose schemas happen to have been computed
at startup rather than written down:

```json
{"name": "delegate_component_analyst",
 "input_schema": {"type": "object",
                  "properties": {"task_id": {"type": "string"},
                                 "goal": {"type": "string"},
                                 "input": {"$ref": "#/$defs/ComponentQuery"}}}}
{"name": "delegate_scout",
 "input_schema": {"type": "object",
                  "properties": {"task_id": {"type": "string"},
                                 "goal": {"type": "string"},
                                 "input": {"$ref": "#/$defs/FreeText"}}}}
```

The Python is one hand-written class. Roles differ in data, not in behaviour — look up the
role, write `spec.json`, enqueue — so all of them share a single `run`, and only `args_model`
varies, built by `create_model` from the role's input contract. Nothing is written to disk
and no file is generated. Adding `[roles.foo]` to the config makes `delegate_foo` appear in
that list the next time a worker starts; deleting the role removes it.

The model therefore sees each role's real input schema, and `input_json: str` is gone — with
it the last use of the one-hop-as-text exception `CLAUDE.md` grants, since the class is no
longer unknown at authoring time, only late-bound.

A single `delegate` taking `role` plus a typed `input` was rejected. A tool has one schema,
so one shared `input` field cannot be `ComponentQuery` and `FreeText` at once. Making it vary
by the `role` value needs a discriminated union, whose JSON Schema is a top-level `oneOf`
while the tool API wants `type: object` with properties. Annotating the field `BaseModel`
instead was also tried and is worse: it is shown to the model as `{"properties": {}}`, it
serialises a populated instance as `{}` from a containing model, and parsing it back yields a
bare `BaseModel` with no fields — the payload is gone before any role lookup could recover
it. Pydantic discriminates on data, and we do not control the user's contract classes, so we
cannot put a tag inside them. Splitting by tool is what makes each schema concrete.

The remaining alternative — one `delegate` with `role` as a runtime `Literal` and the payload
back as `input_json: str` — works and matches what the worker already does with
`AgentSpec[InT]`, but it constrains only the role name and leaves the parent guessing the
payload. That guess failed three times in `r_0004`.

`behaviour`, `contracts`, `turns`, `tool_calls` and `input_json` all go. Three fields remain
on each tool: what to call the task, what it is for, and what to give it. The role is the
tool, so the role name is no longer a field at all.

`goal` stays for the same reason the root keeps `goal_file` beside `input_file`: `AgentSpec`
models the standing instruction and the per-call one separately, `behaviour` is the first,
and a parent still needs to say which of two calls to the same role is the awkward one.

## `spec.json` carries the role, not its name

`AgentSpec` becomes `task_id`, `role: Role`, `goal`, `input` — the whole role embedded, not a
name pointing into the config. `behaviour`, `input_schema`, `answer_schema`, `budget` and the
long-dead `tools` all leave it, because the role holds them.

`Role` therefore lives in `ancalagon/contracts/role.py` as a frozen model, and `Config` holds
`roles: Mapping[str, Role]` only so a worker can build the `delegate_*` tools for the roles it
may spawn. Everything about the agent's *own* shape it reads off its spec.

Embedding rather than referencing freezes a task's terms at the moment it was queued. A role
name would leave `spec.json` a pointer into a file that may have changed since, so editing the
config would silently redefine tasks already sitting in the bus. With the role embedded, an
edit affects only tasks queued afterwards. That recovers most of the immutability given up by
not copying contract modules — what it does not freeze is the contract *source*, since
`{module = "./shapes.py", name = "Component"}` is still a path and editing that file still
changes the shape.

The cost is a few hundred duplicated bytes per task, in a directory that already holds a
transcript.

## The root is a role

`[run] role` names it. `[agent] root_behaviour`, `[run] contract_module` and
`[run] contract_class` are deleted.

`AgentSpec` carries `goal` and `input` separately, and the root has always faked the second
as `FreeText(text=goal)`. Once a root role can declare a structured input contract, something
must fill it, so `[run] input_file` joins `goal_file`: a JSON file validated against the
role's input contract at startup, the same validation a `delegate_*` tool performs on a
child's input. An absent `input_file` on a role whose input is `FreeText` builds it from
the goal, so a quick run still needs only a goal file.

The root then differs from a subagent in one thing: it has no parent, so its goal and input
come from files rather than from a `delegate` call. Every asymmetry that produced the
`free_text.py` crash — the CLI installing one contract where `delegate` installed two —
stops being expressible.

## Contract modules are not copied

Today both `install_contracts` and `Delegate._install` copy a contract module into the task
directory, and `resolve_class` refuses to load anything outside that directory. Both exist
because the path came from a model. With roles the path comes from configuration, so there is
nothing to defend against: the worker resolves the module where the config says it is.
`ClassRef`'s `\.py$` pattern and the escape check go with them.

The cost is provenance. A run no longer freezes the shapes it ran under, so editing
`shapes.py` between a run and its resumption silently changes the contract the later agents
work to. Accepted: the config file is the record, and a mid-run edit is the operator's
problem.

## What this does not do

**It adds no separate mechanism for which roles a role may delegate to.** That constraint
falls out of one tool per role: `tools` names `delegate_<role>` entries like any other tool,
so the role graph is expressed in the same list that grants `read_file`. No `delegates = [...]`
field is needed.

**It does not address coordination cost.** A parent still spends a turn per `check_task`
round, which was 149,000 of the root's 277,000 input tokens in `r_0004`. Roles make that
cost *scoped* — only roles granted `delegate` pay it — but do not reduce it. That is its own
investigation.

**It does not preserve the existing config format.** `[agent]`, `[tools]` and three `[run]`
keys are removed. Existing run directories are not migrated; by convention they do not
matter.
