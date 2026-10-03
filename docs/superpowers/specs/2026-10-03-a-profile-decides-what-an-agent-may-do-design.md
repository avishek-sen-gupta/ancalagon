# A profile decides what an agent may do

Supersedes `2026-10-03-a-profile-per-kind-of-agent-design.md`, which is wrong in three ways: it
splits the protocol in two to avoid stubs, it stubs with `NotImplementedError`, and it passes tool
names where it should pass tools. Its problem statement stands; its design does not.

**Blocked on `2026-10-03-strings-only-at-the-seams-design.md`.** That spec introduces `ToolSpec`,
`BoundTool`, `ToolCategory` and a `Role` holding resolved values, all of which this one is written
against. Implementing this first would mean writing it twice.

## The problem

Eighteen places decide what an agent may do, and every one assumes the same thing: that an agent
answers once and stops. Nothing names that assumption, so changing it means finding all eighteen.

Four of them already discriminate on *what kind of role this is*, using `role.run`:

```
check_contracts.py:35   _run_fault applies only when run != NO_RUN
check_contracts.py:60   _submit_fault exempts a role where run != NO_RUN
spawn_by_run.py:20      chosen = self.default if spec.role.run == NO_RUN else self.deterministic
session_for.py:138      watcher_in: roles whose run == WATCH_FOR, which is what makes watch_file offerable
```

The third settles it: the supervisor already picks a **different executor** by the kind of role. The
concept is load-bearing today, spelled as a field rather than a type, and re-derived at every site.

The other fourteen encode the answering assumption without discriminating at all — `_submit_fault`,
`_answer_file_fault`, `_content_fault`, `build_registry`'s injected `idle`, `submitting()`'s silent
precedence, `_loop`'s `if final and outstanding`, `_forced`, both branches of `_declarations`,
`_system`'s "that tool is the only way to answer", `_final_instruction`, `_continue_instruction`,
`Idle.run`'s refusal, and `_outcome_of_use`'s use of `final` to turn a `Completed` into an
`Exhausted`.

## What this is not

**Not a change to how an outcome is classified.** Nudge-or-fail, whether a call is charged, which
`Payload` means which `Outcome`, whether a final turn may repeat, and how a turn that answered
nothing is reported all need a `Reply` or the `ran` results rather than a `Turn`. They stay in
`Session`. A profile decides **what to send**; the session classifies **what came back**.

**Not ownership of the loop.** `_loop` keeps its shape: deliver notes, build the turn, ask the
profile, call the model, run tools, classify.

**Not spawner selection.** `spawn_by_run.py:20` keeps keying on `role.run`, which leaves two sources
of truth for the same fact. Recorded as a debt, deliberately deferred.

**Not backward compatible.** `profile` is required on every role, with no default and no derivation
from `tools`. Deriving it would restore the implicit coupling this removes.

**Not a new extension mechanism.** A role already names dotted refs to arbitrary code in three places
— `before`, `after`, `run` — and the seams spec moves all of that resolution into the loader.
`resolve_profile` joins that family.

## Design

### `Turn` — the state every decision sees

One frozen value, rebuilt once per pass of `_loop`:

```python
@dataclasses.dataclass(frozen=True)
class Turn:
    spec: TaskSpec
    agent_id: int
    output_class: type[pydantic.BaseModel]
    offered: tuple[BoundTool, ...]
    remaining: Budget
    spent: Spend
    outstanding: tuple[int, ...]
    uncollected: tuple[int, ...]
    tries: int
    delivered: Delivery
    workspace: Workspace

    @property
    def final(self) -> bool:
        return self.remaining.turns_exhausted

    def bound(self, spec: ToolSpec, /) -> BoundTool | NoTool:
        ...                      # a dict hit; ToolSpec is hashable
```

`offered` holds **bound tools, not names** — which is the whole reason this spec waits for the seams
work. It is what makes `af0dcde`'s crash unexpressible rather than merely guarded: a profile that
returns a tool can only return one it was handed, so `forces` cannot name something the registry does
not hold, and the `COLLECT in self.registry.names()` check deletes.

`final` is derived, never stored; storing it would let the two disagree. `tries` is a `_loop` local
today, introduced by `5e27e00`; `forces` needs it, so it joins the representation.

There is no terminal-tool field. That belongs to the profile.

### One protocol, with defaults

```python
class Profile(typing.Protocol):
    tools: tuple[ToolSpec, ...] = ()

    def faults(self, name: str, role: RoleFromConfig, /) -> str:
        return ""

    def halts(self, turn: Turn, /) -> Outcome[pydantic.BaseModel] | Pending:
        return PENDING

    def forces(self, turn: Turn, /) -> BoundTool | NoTool:
        return NO_TOOL

    def offers(self, turn: Turn, /) -> tuple[BoundTool, ...]:
        return turn.offered

    def mechanics(self, turn: Turn, /) -> str:
        return ""

    def instructs(self, turn: Turn, /) -> str:
        return ""

    def nudges(self, turn: Turn, /) -> str:
        return ""
```

Every method takes `Turn` and nothing else. `forced` is **not** a parameter even though four
decisions need it, because `forces(turn)` is itself a function of `Turn` — so `offers` and
`instructs` call it rather than receiving it, and the protocol stays free of transients.

The bodies return values rather than raising. `NotImplementedError` is a side-channel return, and the
codebase answers this question with null objects everywhere else: `NO_BUS`, `NO_SINK`, `NOTHING`,
`PENDING`, `NoIdle`. `Payload.text_for_model` raising is the exception and not a model to copy.

`faults` takes a `RoleFromConfig`, not a `Role`, because it runs at the seam: a core `Role` that
exists has already been validated, so there is nothing left for it to object to.

Implementations inherit `Profile` rather than satisfying it structurally, per `CLAUDE.md`, so a
mistake lands on the broken class instead of on the distant list where profiles meet an annotation.

### The defaults are `Standing`

Never halt, never force, offer everything the role declared, find no faults, say nothing extra.
That is the persistent profile almost exactly, so `Standing` overrides only three things:

```python
class Standing(Profile):
    def __init__(self, catalogue: Catalogue, role: RoleFromConfig):
        self.tools = (catalogue.spec_for(Idle, role),)

    def faults(self, name: str, role: RoleFromConfig, /) -> str:
        ...                      # refuses an answer other than the FREE_TEXT default

    def mechanics(self, turn: Turn, /) -> str:
        return (
            "You do not answer and you do not finish. You work, you write what you have "
            "to the files you own, and when there is nothing left to do you call idle. "
            "Idling ends this turn; you will be started again when something arrives for "
            "you, with this conversation intact."
        )
```

Which says something the previous shape obscured: **answering is the specialised behaviour and
persisting is the base case.** The harness has had it backwards since there was only one kind of
agent.

`Deterministic` is thinner still — it overrides `faults` and nothing else, because `tools = ()` is
already the default and a role with a `run` function never constructs a `Session`. Its inherited
`halts`, `forces` and the rest are never called, and if one ever were it would return a harmless
value rather than crashing.

### The four profiles

| | `Answering` | `AnsweringAsFile` | `Standing` | `Deterministic` |
|---|---|---|---|---|
| `tools` | specs for `SubmitAnswer`, `CollectTask`, `Idle` | specs for `SubmitAnswerAsFile`, `CollectTask`, `Idle` | a spec for `Idle` | `()` |
| `faults` | refuses a `run` ref | refuses a `run` ref; requires `answer == AnswerFile` and `answer_file` declared | refuses a non-default `answer` | requires `run`; signature must match declared `input`/`answer` |
| `halts` | `Idling` when `final and outstanding` | same | inherited: `PENDING` | inherited |
| `forces` | `collect_task` while uncollected and `tries`, else its terminal tool | same | inherited: `NO_TOOL` | inherited |
| `offers` | today's exclusion logic | same | inherited: all of `turn.offered` | inherited |
| `mechanics` | call the tool, here is the schema | same, with the file contract | the standing paragraph | inherited: `""` |
| `instructs` | answer now from what you know | same | inherited: `""` | inherited |
| `nudges` | answers only arrive through the tool | same | inherited: `""` | inherited |

`Answering` and `AnsweringAsFile` are separate profiles rather than one with a branch, which is what
finally deletes `submitting()`: each names its own terminal tool in `tools`, so nothing infers which
one a role meant and nothing resolves a precedence.

### Lifecycle tools

`tools` holds `ToolSpec`s, and a profile is **constructed once per role** by the loader, which is
what makes that possible:

```python
# the loader, once per role
profile = resolve_profile(role.profile)(catalogue, role)
tools = tuple(catalogue.spec_for(name, role) for name in role.tools) + profile.tools


class Answering(Profile):
    def __init__(self, catalogue: Catalogue, role: RoleFromConfig):
        self.submit = catalogue.spec_for(SubmitAnswer, role)
        self.collect = catalogue.spec_for(CollectTask, role)
        self.tools = (self.submit, self.collect, catalogue.spec_for(Idle, role))

    def forces(self, turn: Turn, /) -> BoundTool | NoTool:
        if turn.uncollected and turn.tries > 0:
            return turn.bound(self.collect)
        return turn.bound(self.submit)
```

Every profile takes the same two arguments — `(catalogue, role)` — and picks what it needs, so
pluggability survives a uniform constructor. Holding the specs is also what lets `forces` and `offers`
identify a tool at all: they look up `turn.bound(self.submit)` rather than having to recognise a
`BoundTool` as the one they meant.

Some of those specs genuinely vary per role and some do not — `SubmitAnswer` sets
`self.args_model = output_class` and builds its `description` from that class's fields, while
`SubmitAnswerAsFile` has `args_model = AnswerFile` as a class attribute. Mixed, which is why the
catalogue builds all of them rather than anything inferring which kind it is dealing with.

`build_registry`'s `wanted` then reduces to `role.tools` with nothing to union, and
`wanted = set(spec.role.tools) | {Idle.name}` — that list hardcoded for the only profile that existed
— goes with it, along with `withheld = TERMINAL_TOOLS - {submitting(...)}` and `submitting()` itself.

A role that also lists a lifecycle tool is a mistake and is **not** refused: the union absorbs it and
nothing downstream can tell. Deferred by decision.

### Validation moves into the profile

| fault | where it goes |
|---|---|
| `_contract_fault` | already deleted by the seams spec — a `Role` holds no refs |
| `_hook_fault` | stays, consulting `role.profile.tools` for the lifecycle half |
| `_submit_fault` | `Answering` / `AnsweringAsFile` / `Standing`'s `faults` |
| `_answer_file_fault` | `AnsweringAsFile.faults` |
| `_content_fault` | `AnsweringAsFile.faults` |
| `_run_fault` | `Deterministic.faults` |

`_submit_fault`'s `if role.run != NO_RUN: return ""` exemption disappears rather than moving: a
deterministic role is not exempted from needing a terminal tool, it has a profile that never required
one.

### Selection is explicit

`RoleFromConfig.profile: ClassRefFromConfig`, required, no default. `Role.profile: Profile`, resolved
by the loader. `resolve_profile(ref) -> Profile` refuses anything that is not one.

```toml
[roles.investigator]
profile = { module = "ancalagon.profiles.answering", name = "Answering" }
behaviour = "..."
tools = ["read_file", "ripgrep", "find_symbol"]
budget = { turns = 14, tool_calls = 35 }
```

Note what left: `submit_answer` is no longer in `tools`, because `Answering` brings it.

### What the session keeps

`_loop`'s shape, the transcript, metering, the letterbox, budget spending, `_run_tools`' cost rule,
`_uncalled`'s branch, `_settled`, `_outcome_of_use`, `_refused`, `_ended`.

Two mechanical consequences of tools replacing names:

- `_declarations` becomes `[t.spec.declaration for t in role.profile.offers(turn)]` and stops calling
  `registry.get` at all.
- `LLM.complete`'s `force_tool` changes from `str` to `BoundTool | NoTool`, rendered to a name in
  `litellm_client` where the wire needs one.

`Idle.run`'s refusal goes, because availability is `offers`' answer now. `Idle` still reads the bus to
populate `Idled.waiting_for` — data for its own result, not a decision — and `Idled.text_for_model`
branches for an empty `waiting_for`, which otherwise reads *"idling until one of agents [] finishes"*.

## Known debts

**`spawn_by_run` is a second source of truth.** It picks an executor by `role.run`, so a role could
declare `Answering` and still carry a `run` ref. `Answering.faults` refusing one closes the gap by
validation rather than by construction, which is weaker. Out of scope here.

**`watcher_in` stays keyed on `run == WATCH_FOR`.** It asks "is there a watcher in this config", which
is finer-grained than "what kind of role is this", so a profile cannot answer it.

**A role listing a lifecycle tool is silently absorbed.** Stated above.

**Writing a profile is writing policy.** A bad one can offer nothing, or return prose telling an
agent to do something impossible, and nothing validates prose. Same exposure `before`, `after` and
`run` already carry, one grain larger.

**Defaults make a forgotten method quiet.** A profile that neglects `faults` validates nothing, and
nothing reports it. That is the cost of returning values instead of raising, accepted deliberately.

## Testing

1. **`tests/unit/test_turn.py`, one behaviour.** `Turn` is built from a session's state, `final`
   tracks `remaining`, and `offered` holds bound tools so a profile cannot name an unbound one.
2. **`tests/unit/test_profiles.py`, one behaviour per profile.** Each method asserted against
   concrete values on a hand-built `Turn`: `Answering.forces` returning the `collect_task` **tool**
   with an uncollected child and its terminal tool without one; `Standing.forces` returning `NO_TOOL`
   and `Standing.halts` returning `PENDING` with outstanding children; `Deterministic.faults`
   refusing a missing `run`. No `FakeLLM` anywhere, because nothing in the protocol touches a model.
3. **`tests/unit/test_session_loop.py` extends.** Its existing assertions on offered tools and forced
   names must pass **unchanged** once `Answering` is wired in. That is the proof the refactor
   preserves behaviour, and the reason commits 1 and 2 are separate from commit 4.
4. **`tests/unit/test_hooks.py` extends** for `_hook_fault` consulting `role.profile.tools`: a hook on
   the terminal tool resolves for an `Answering` role that does not list it, and is refused for a
   `Standing` role, which has no such tool.
5. **`tests/unit/test_config_load.py` extends**: a role with no `profile` is refused; a `profile`
   naming a class that is not a `Profile` is refused with a message naming the class.
6. **`tests/integration`**, whole suite.
7. **Mutation-check every new test.** Make `Answering.forces` always return its terminal tool; make
   `offers` return `turn.offered` unfiltered; make `faults` always return `""`; make `Turn.final` a
   stored field set to `False`.

## Commits

Four. The first two change no behaviour.

1. **`Turn`, and the session computing it.** The decision methods keep their bodies and read their
   inputs from `Turn`. No protocol, no profiles, no config change. Every existing test passes
   untouched; if one does not, the refactor is wrong.
2. **`Profile`, `Answering`, `AnsweringAsFile`, `resolve_profile`, `profile` on the role.** The
   session delegates the six turn decisions. `Answering` encodes exactly today's policy, so
   `test_session_loop.py`'s assertions stand unchanged. Configs gain `profile` and lose their terminal
   tool from `tools`. The big mechanical commit, and the one to review hardest.
3. **Validation moves, and `Deterministic`.** The four faults become profile `faults`, `submitting()`
   and `withheld` delete, `_hook_fault` consults the profile, `af0dcde`'s guard goes, and
   `spawn_by_run`'s debt is recorded in `docs/architecture.md` rather than fixed.
4. **`Standing`.** The new capability: `Idle.run`'s refusal removed, `Idled.text_for_model`'s branch,
   and a standing role in a config with an integration test. Everything before this is a refactor;
   this is the commit that adds something.
