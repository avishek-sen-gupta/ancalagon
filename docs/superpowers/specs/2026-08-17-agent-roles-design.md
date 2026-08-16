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

`prose` is built in: `FreeText` on both sides, every tool, the run's default budget. It is
the freestyling agent, and it is still under contract.

`tools` is per-role, replacing the global `[tools] enabled`. A role whose `tools` omits
`delegate` cannot spawn anything — which is how a program pins a subtree to depth 1 without
a new mechanism.

`budget` is authoritative and fixed. A parent does not choose it and cannot be wrong about
it. This means total work is no longer bounded by the root's budget: a parent with 8 turns
may spawn ten children of a 20-turn role. It is bounded instead by the role graph and
`max_depth`, and that is the config author's business. `Allowance`, `WithinParent` and
`AsAsked` are deleted.

## What `delegate` becomes

Roles are known at worker startup, before the tool schema is built. So `delegate`'s argument
model is generated then: one variant per declared role, discriminated on `role`, built with
`create_model` exactly as `AgentSpec[InT]` and `Completed[OutT]` are built today.

```
delegate(role: "component_analyst", task_id: str, input: ComponentQuery)
delegate(role: "prose",             task_id: str, input: FreeText)
```

The model sees each role's real input schema. `input_json: str` is gone, and with it the
last use of the one-hop-as-text exception `CLAUDE.md` grants: the class is no longer unknown
at authoring time, only late-bound, which is what generics are for.

`behaviour`, `contracts`, `turns` and `tool_calls` all leave `DelegateArgs`. Three fields
remain: which role, what to call it, what to give it.

## The root is a role

`[run] role` names it. `[agent] root_behaviour`, `[run] contract_module` and
`[run] contract_class` are deleted.

`AgentSpec` carries `goal` and `input` separately, and the root has always faked the second
as `FreeText(text=goal)`. Once a root role can declare a structured input contract, something
must fill it, so `[run] input_file` joins `goal_file`: a JSON file validated against the
role's input contract at startup, the same validation `delegate` performs on a child's input.
An absent `input_file` on a role whose input is `FreeText` builds it from the goal, so a
quick run still needs only a goal file.

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

**It does not constrain which roles a role may delegate to.** `tools` decides whether a role
can delegate at all; beyond that any declared role is reachable. A `delegates = [...]` field
is a plausible next constraint and is deliberately not built.

**It does not address coordination cost.** A parent still spends a turn per `check_task`
round, which was 149,000 of the root's 277,000 input tokens in `r_0004`. Roles make that
cost *scoped* — only roles granted `delegate` pay it — but do not reduce it. That is its own
investigation.

**It does not preserve the existing config format.** `[agent]`, `[tools]` and three `[run]`
keys are removed. Existing run directories are not migrated; by convention they do not
matter.
