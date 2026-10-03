# Strings only at the seams

## The problem

A string enters this codebase at two places — a TOML document and a model's reply — and then travels
inward, unresolved, until something needs what it stands for. Every consumer resolves it again.

`Role` is the clearest case. It holds `ClassRef`s for `input`, `answer` and `answer_file`,
`FunctionRef`s for hooks and `run`, and tool **names** in `tools`. None of those is what the core
wants; each is a pair of strings waiting to be turned into a class, a callable or a tool. So:

- `session_for` calls `resolve_class(spec.role.answer)` on every agent construction.
- `check_contracts._contract_fault` calls `resolve_class` on all three refs to find out whether they
  resolve at all, and reports a fault built from the two strings.
- `bound_for` looks hooks up with `role.before.get(tool.name, ())` — a dict keyed by tool name.
- `build_registry` checks `wanted - {t.name for t in available}` and raises *"role names unknown
  tools"* from a hand-built message.
- `session_for.py:155` reconstructs `f"delegate_{name}"` to discover which roles an agent may spawn.
- `session_for.py:176` asks `t.name.startswith("delegate_")` to find delegate tools for the depth
  cap, which is the prohibition in `docs/guidelines/design-principles.md` stated verbatim: *"Never
  use string prefixes, patterns, or regex to deduce what a value represents."*
- `fork_command` rebuilds the whole delegate name set with `frozenset(delegate_name(role) for role in
  config.roles)` and threads it through `forked(messages, at, delegates, clock)` so `orphaned` can
  recognise a delegation in a transcript.

Three of those reconstruct a naming convention. One of them is explicitly forbidden. And the cost is
not only tidiness: `af0dcde` fixed a crash where `_forced` named `collect_task` while
`build_registry` had no reason to bind it, because a name is not a thing and nothing connected the
two.

Fourteen types are `enum.StrEnum`, which compare equal to their own values and interpolate without
`.value`. That makes every one of them a string that happens to be typed, and the implicit
conversion is what lets a name leak past a boundary unnoticed.

## What this is not

**Not the profile refactor.** `2026-10-03-a-profile-per-kind-of-agent-design.md` is written against
bare strings, two protocols and `NotImplementedError` stubs, all three of which are now wrong. It
needs its own revision, which sits **on top of** this spec and is not part of it. This one is the
prerequisite.

**Not a rename.** `RawRole` becoming `RoleFromConfig` is the visible part, but the change is that the
two types stop holding the same kinds of value. A rename alone would leave `Role` full of refs.

**Not a new boundary.** The seams already exist: `load.py` and `from_raw.py` for the document,
`litellm_client.py` for the provider. Nothing new is introduced; what changes is that they become
the *only* places a string is read for its meaning.

**Not a validation layer.** Several checks disappear rather than move. A core `Role` that exists is
already resolved, so there is nothing left to validate about its refs.

**Not an exemption for prose.** `CLAUDE.md` already draws this line — *"Prose bound for a prompt is
text; a record with fields is not."* `Text.text`, `role.behaviour`, a tool's `description`, a
profile's instruction text and a fault message are prose and stay `str`. They are text because a
human or a model reads them, not because something will later look up what they mean.

## Design

### The rule

A string is read for its meaning in exactly one place per seam, and what it resolved to is what
travels inward. Stated as three claims that the precommit guards enforce:

1. No `str` field or parameter in `ancalagon/` outside a seam module, except prose.
2. No `enum.StrEnum` anywhere.
3. A seam type is named for its seam, so a reader can tell at the import.

### Seam types are named for their seam

| today | becomes | why |
|---|---|---|
| `RawRole`, `RawWorkspace`, `RawModel`, `RawLimits`, `RawRun`, `RawSandbox`, `RawLog`, `RawWeb`, `RawClassRef`, `RawBudget` | `RoleFromConfig`, `WorkspaceFromConfig`, … — `*FromConfig` | `Raw` says "unprocessed" without saying where it came from |
| `RawConfig` | `DocumentFromConfig` | `ConfigFromConfig` stutters, and it is the whole TOML document rather than one table |
| `ToolUse` | `ToolUseFromModel` | it holds a name the model chose, which may name nothing |
| `WireMessage`, `WireToolCall`, `WireFunction`, `WireTextBlock`, `WireUsage` | unchanged | `Wire` already names its seam unambiguously |

All eleven `Raw*` types move together. Renaming one of them is worse than renaming none, because ten
would then say `Raw` and one `FromConfig`.

### `ToolSpec` and `BoundTool`

A tool's identity becomes an object. The split is forced by lifetime: a tool's *declaration* is
knowable at config load, while its *invocation* closes over a bus, an agent id and a clock that are
per-agent.

```python
class ToolCategory(enum.Enum):
    FILES = "files"
    SEARCH = "search"
    PARSE = "parse"
    ARTIFACTS = "artifacts"
    DELEGATE = "delegate"
    SUBMIT = "submit"
    LIFECYCLE = "lifecycle"
    ...


class ToolSpec(pydantic.BaseModel, frozen=True):
    category: ToolCategory
    cost: int
    declaration: ToolSchema          # the only place a tool's name exists


class BoundTool(pydantic.BaseModel, frozen=True):
    spec: ToolSpec
    invoke: collections.abc.Callable[[str, ToolContext], ToolResult]
```

`ToolSpec` carries **no `name` field.** The name lives in `declaration`, which is the object
serialised to the provider, so the single route to a tool's name as text is
`spec.declaration.name` at the adapter. `ToolSchema` is a seam type by purpose and keeps its
strings.

`ToolSpec` carries no `parameters` field either: `declaration.parameters` already holds the args
model, and duplicating it would let the two disagree.

**The delegate target is not on the spec.** A `delegates_to: Role` would be a reference cycle the
moment two roles delegate to each other, and it would make `ToolSpec` unhashable, since `Role` holds
`Mapping`s — and it must be hashable, because the hook maps are keyed by spec. So the loader keeps a
`Mapping[ToolSpec, Role]` for delegate specs, built once every role is resolved and therefore
cycle-free.

That is what deletes `session_for.py:155` and `:176`: the depth cap reads
`spec.category is ToolCategory.DELEGATE`, and the spawnable set is a lookup in that mapping instead
of a reconstructed `f"delegate_{name}"`.

`Tool` collapses from four attributes to one:

```python
class Tool[ArgsT: pydantic.BaseModel](typing.Protocol):
    spec: ToolSpec

    def run(self, args: ArgsT, ctx: ToolContext) -> ToolResult: ...
```

Thirty-two tools declare `name`, `description`, `cost` and `args_model` as class attributes today;
they declare one `ToolSpec` instead. `bind_tool` stops calling `schema_of` because the schema is
already in the spec, and `bound_for` looks hooks up by spec rather than by `tool.name`.

### The catalogue is the seam's lookup table

Most specs are fixed, but four kinds are per-role: `delegate_<role>` narrows `DelegateArgs` by the
target role's `input`; `submit_answer` and `submit_answer_as_file` take the role's answer class; and
`watch_file` depends on which role is the watcher. All four are knowable at config load, because the
loader has every resolved class.

So the loader owns a catalogue — the one mapping from a TOML tool name to a `ToolSpec` — and builds
the per-role specs as it goes. `build_registry`'s `unknown` check and its hand-built *"role names
unknown tools"* message both disappear: an unknown name fails in the catalogue lookup, at the seam,
with the position in the document that Pydantic already reports.

### `Role` holds what the refs resolved to

```python
class RoleFromConfig(pydantic.BaseModel, frozen=True):
    behaviour: str
    tools: list[str]
    profile: ClassRefFromConfig
    input: ClassRefFromConfig = ...
    answer: ClassRefFromConfig = ...
    before: dict[str, list[ClassRefFromConfig]] = {}
    ...


class Role(pydantic.BaseModel, frozen=True):
    behaviour: str                                  # prose
    tools: tuple[ToolSpec, ...]
    profile: Profile
    input: type[pydantic.BaseModel]
    answer: type[pydantic.BaseModel]
    before: collections.abc.Mapping[ToolSpec, tuple[Before, ...]]
    after: collections.abc.Mapping[ToolSpec, tuple[After, ...]]
```

Every `ToolSpec` field is hashable — an `Enum`, an `int`, and a `ToolSchema` whose `parameters` is a
class — which is what lets it key those maps, and why the delegate target lives in the loader's
mapping rather than on the spec.

`resolve_class`, `resolve_run`, `resolve_before`, `resolve_after` and `resolve_profile` all move into
the seam and stop being reachable from the core. Hook dicts are keyed by `ToolSpec`, so a hook
declared for a tool the role does not have cannot be constructed rather than being caught later.

**This deletes `_contract_fault`.** A core `Role` cannot hold an unresolvable ref, because it holds
no refs. What was a fault becomes a parse failure at the seam.

### A tool call is resolved before it is run

```python
class ToolUseFromModel(pydantic.BaseModel, frozen=True):   # a Block; persisted
    kind: typing.Literal[BlockKind.TOOL_USE] = BlockKind.TOOL_USE
    id: str
    name: str
    arguments: str


class ToolUse(pydantic.BaseModel, frozen=True):            # internal; never persisted
    id: str
    tool: BoundTool
    arguments: str
```

The transcript keeps the from-model form, and that is correct rather than a compromise: a loaded
transcript genuinely knows only names, because the tool set can differ between attempts, and
`ToolSpec.parameters` is a class reference that would not round-trip as JSON anyway.

Resolution becomes an explicit step between reading a reply and running its calls, and the
"model named a tool that does not exist" branch moves there from inside `_run_tools`, which is where
a boundary failure belongs. It also types a distinction that is currently invisible: `_ended(ran,
uses)` takes two lists because a call naming an unknown tool, or one refused for want of budget,
appears in `uses` and never in `ran`. One becomes `Sequence[ToolUseFromModel]`, the other resolved
pairs.

`Registry` keys on the wire name, because that is what a model sends. That is the one hop where a
name crosses inward, and it is resolved immediately.

### `StrEnum` becomes `Enum`

All fourteen: `agent_status`, `answer_status`, `block_kind`, `delivery`, `event_source`, `line_kind`,
`message_role`, `outcome_kind`, `strategy`, `document_format`, `json_op`, `git_operation`,
`edge_kind`, `node_kind`.

A grep for implicit use — `X.MEMBER == "literal"` comparisons and bare interpolation — found none, so
`.value` is already written at every boundary and the change is mechanical. Two things need
verifying rather than assuming: that `kind: typing.Literal[BlockKind.TOOL_USE]` still works as a
Pydantic discriminator with a plain `Enum`, and that enum fields still serialise to their value so
`transcript.jsonl` and `bus.db` stay byte-identical.

### The guards

`precommit-scripts/` already holds `check-type-hygiene`, which bans `Any` and `object`. Two more join
it, because a rule nobody enforces comes back:

- **no `enum.StrEnum`** anywhere under `ancalagon/`.
- **no `str` annotation** under `ancalagon/` outside a declared list of seam modules, with a
  `# seam:` comment as the only suppression and prose fields exempted by an allow-list of names.

The second needs its exemption list written down rather than inferred, which is the point: an
exemption that has to be named is one a reviewer can argue with.

## Known debts

**The prose allow-list is a judgement call.** `behaviour`, `description`, `text`, `question`,
`reason`, `summary`, `error`, and whatever a profile returns. Any of those could become a wrapping
type later; none of them needs to now, and the guard will read as arbitrary until someone asks why
`summary` is prose and `name` is not. The answer is that nothing looks up what a summary means.

**`spawn_by_run` still keys on `role.run`.** It chooses an executor by inspecting a ref, which after
this change is one of the few places a core value is read for what it stands for. Left alone here
because it belongs to the profile revision.

**`ToolSpec` has no name and that will be inconvenient.** Logging, error messages and `trace` all
want a tool's name, and all of them will reach through `spec.declaration.name`. That is one hop
rather than a field, and it is deliberate — but it will read as indirection until the reason is
remembered.

## Testing

1. **`tests/unit/test_config_load.py` extends.** An unknown tool name is refused by the catalogue
   with the name and the role; an unresolvable `ClassRefFromConfig` is refused at load rather than by
   `check_contracts`; a hook declared for a tool the role does not list is refused when the hook map
   is keyed.
2. **`tests/unit/test_tools.py` extends** for `ToolSpec`: a delegate spec's `category` is `DELEGATE`
   and the loader's mapping resolves it to the target `Role`. The depth cap
   test asserts delegate tools are withheld **by category**, with no name in the assertion.
3. **`tests/unit/test_fork.py` extends.** `forked` no longer takes `delegates`, and `orphaned`
   recognises a delegation from a persisted `ToolUseFromModel` by resolving it, not by membership in
   a reconstructed set.
4. **One behaviour per renamed enum is not worth a test.** The suite already asserts serialised
   values in `test_bus.py`, `test_trace.py` and `test_session_loop.py`; those assertions passing
   unchanged **is** the test that `Enum` serialises as `StrEnum` did.
5. **`tests/integration`**, whole suite. Forty seconds, and two plans in a row let a regression
   through by narrowing it to the one test they were about.
6. **The guards get their own tests**, in the shape `precommit-scripts/` already uses: a fixture file
   with a `StrEnum` and one with a bare `str` field each fail, and a seam module with both passes.
7. **Mutation-check every new test.** Make the catalogue accept an unknown name; make the depth
   cap withhold nothing; make the `str` guard skip every file.

## Commits

Six, in this order. The first two are independent of everything else and could land on their own.

1. **`StrEnum` → `Enum`, and its guard.** Fourteen declarations, no behaviour change, and the
   existing serialisation assertions are the proof. Lands first because it is the only unit with no
   dependencies.
2. **The `Raw*` → `*FromConfig` rename.** Mechanical, eleven types, no field changes. Separate so
   that the next commit's diff is about types moving rather than names changing.
3. **`ToolCategory`, `ToolSpec`, `BoundTool`, and `Tool` collapsing to one attribute.** Thirty-two
   tools change their declaration. `session_for.py:176` reads a category, `:155` reads the loader's
   mapping, `fork` loses its `delegates` parameter, and `af0dcde`'s guard goes. Behaviour
   identical throughout; the tests say so.
4. **The catalogue, and `Role` holding resolved values.** The seam resolves everything;
   `_contract_fault` and `build_registry`'s `unknown` check are deleted. This is the commit that
   moves the boundary, and the one to review hardest.
5. **`ToolUseFromModel`, internal `ToolUse`, and resolution as a step.** The transcript's block type
   is renamed, so this commit touches `history.py`, `demote.py`, `litellm_client.py` and `trace`.
   A transcript written before it still loads, because the persisted shape is unchanged.
6. **The no-`str` guard and its exemption list.** Last, because it can only pass once everything
   above has landed, and writing it earlier would mean maintaining a growing list of temporary
   suppressions.

The profile revision follows as its own spec, written against `ToolSpec` and `BoundTool` rather than
against names.
