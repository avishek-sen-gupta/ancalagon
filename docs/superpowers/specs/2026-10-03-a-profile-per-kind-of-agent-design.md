# A profile per kind of agent

## The problem

Eighteen places decide what an agent may do, and every one of them assumes the same thing: that an
agent answers once and stops. Nothing names that assumption, so changing it means finding all
eighteen.

Four of them already discriminate on *what kind of role this is*, using `role.run` as the
discriminator:

```
check_contracts.py:35   _run_fault applies only when run != NO_RUN
check_contracts.py:60   _submit_fault exempts a role where run != NO_RUN
spawn_by_run.py:20      chosen = self.default if spec.role.run == NO_RUN else self.deterministic
session_for.py:138      watcher_in: roles whose run == WATCH_FOR, which is what makes watch_file offerable
```

The third is the one that settles the argument: the supervisor already picks a **different
executor** depending on the kind of role. So the concept is load-bearing today; it is simply
spelled as a field rather than a type, and every site that needs it re-derives it.

The remaining fourteen encode the answering assumption without discriminating at all:

| site | the policy it hardcodes |
|---|---|
| `check_contracts._submit_fault` | a session role must name exactly one terminal tool |
| `check_contracts._answer_file_fault` | `answer` must be `AnswerFile` when the file tool is named |
| `check_contracts._content_fault` | `answer_file` declared iff the file tool is named |
| `session_for.build_registry` | `wanted` gets `idle` injected; `withheld` subtracts the losing terminal tool |
| `submitting()` | which terminal tool, resolved by silent precedence |
| `Session._loop` | `if final and outstanding: return Idling(...)` |
| `Session._forced` | collect before answering, `COLLECT_TRIES` deep, if the registry has it |
| `Session._declarations` | `idle` withheld when nothing is outstanding; submit withheld when anything is |
| `Session._declarations` (final) | exactly one tool, the forced one |
| `Session._system` | "that tool is the only way to answer", plus a rendered answer schema |
| `Session._final_instruction` | answer now from what you know |
| `Session._continue_instruction` | answers only arrive through the submit tool |
| `Idle.run` | refuse unless there are live children |
| `_outcome_of_use` | `final` is what turns a `Completed` into an `Exhausted` |

**The cost of that scattering is not hypothetical.** `af0dcde` fixed a crash introduced the same
day: `_forced` could name `collect_task` while `build_registry` had no reason to include it, because
the forcing policy and the registry contents are decided in two places with nothing connecting
them. A role that delegated without naming `collect_task` died on its final turn with
`KeyError: unknown tool collect_task`. One object owning both would have made it unexpressible.

## What this is not

**Not a change to how an outcome is classified.** Decisions 13 to 17 in the enumeration — nudge or
fail, whether a call is charged, which `Payload` means which `Outcome`, whether a final turn may
repeat, how a turn that answered nothing is reported — need the `Reply` or the `ran` results, not
just `Turn`. They stay in `Session`. A profile decides **what to send**; the session classifies
**what came back**.

**Not ownership of the loop.** `_loop` keeps its shape: deliver notes, compute state, ask the
profile, call the model, run tools, classify. A profile answers questions inside that loop and does
not get to restructure it.

**Not spawner selection.** `spawn_by_run.py:20` keeps keying on `role.run`. Making it a profile
question is correct and is deliberately deferred — see *Known debts*, because it leaves two sources
of truth for the same fact.

**Not backward compatible.** `profile` is required on every role, with no default and no derivation
from `tools`. Deriving it would reintroduce exactly the implicit coupling this removes. Every
shipped config and every test config declares one.

**Not a new extension mechanism.** A role already names dotted refs to arbitrary code in three
places — `before`, `after`, `run` — and `resolve_class`, `resolve_run`, `resolve_before` and
`resolve_after` already exist as a family. `resolve_profile` is the fifth, at a larger grain.

**It supersedes `2026-10-03-an-agent-that-never-answers-design.md`.** That spec deletes three gates
so a standing agent becomes expressible. Under a profile those gates are not deleted, they are
*asked*, and its design section no longer applies. Its problem statement and its account of why
quiescence already works both stand.

## Design

### `Turn` — the state every decision sees

One frozen value, rebuilt once per pass of `_loop`:

```python
@dataclasses.dataclass(frozen=True)
class Turn:
    spec: TaskSpec
    agent_id: int
    output_class: type[pydantic.BaseModel]
    offered: tuple[str, ...]
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
```

Three things about it.

`final` is derived, never stored. It is `remaining.turns_exhausted`, and storing it would let the
two disagree.

`offered` is tool **names**, not a `Registry` and not `ToolSchema`s. The profile answers in names
and the session resolves declarations, so a profile never touches the registry and cannot return a
schema for a tool that is not bound.

`tries` is today a local in `_loop`, introduced by `5e27e00`. `forces` needs it, so it becomes part
of the representation rather than a variable the loop keeps to itself.

There is no `submit` field, although `Session` has one today. The terminal tool is the profile's,
not the turn's.

### The protocol

```python
class Profile(typing.Protocol):
    tools: tuple[str, ...]

    def faults(self, name: str, role: Role, /) -> str: ...


class SessionProfile(Profile, typing.Protocol):
    def halts(self, turn: Turn, /) -> Outcome[pydantic.BaseModel] | Pending: ...
    def forces(self, turn: Turn, /) -> str: ...
    def offers(self, turn: Turn, /) -> tuple[str, ...]: ...
    def mechanics(self, turn: Turn, /) -> str: ...
    def instructs(self, turn: Turn, /) -> str: ...
    def nudges(self, turn: Turn, /) -> str: ...
```

Two protocols, not one, and the split is the static/runtime seam rather than taste. `check_contracts`
sees a `Role` and needs only `Profile`; `Session` sees a live turn and needs `SessionProfile`.
`Deterministic` is a `Profile` and nothing more, because a role with a `run` function never
constructs a `Session` — so it has no `Turn` methods to stub out, and nothing asks it for any.
`Answering`, `AnsweringAsFile` and `Standing` are `SessionProfile`s.

`tools` is a class attribute rather than a method, following `Tool`, which declares `name`,
`description`, `cost` and `args_model` the same way. The list is fixed per profile; nothing about a
particular role changes it.

Every method takes `Turn` and nothing else. `forced` is **not** a parameter even though four
decisions need it, because it is derivable: `forces(turn)` reads only `Turn`, so `offers` and
`instructs` call it rather than receiving it. That is what keeps the whole protocol transient-free
and is why no method needs a `Reply` or a `ran`.

Implementations inherit `Profile` rather than satisfying it structurally, per `CLAUDE.md`: the error
then lands on the broken class instead of on the distant list where profiles meet an annotation.

### The four profiles

| | `Answering` | `AnsweringAsFile` | `Standing` | `Deterministic` |
|---|---|---|---|---|
| `tools` | `submit_answer`, `collect_task`, `idle` | `submit_answer_as_file`, `collect_task`, `idle` | `idle` | `()` |
| `faults` | refuses a `run` ref | refuses a `run` ref; requires `answer == AnswerFile` and `answer_file` declared | refuses an `answer` other than the `FREE_TEXT` default — nothing would check it | requires `run`; signature must match declared `input`/`answer` |
| `halts` | `Idling` when `final and outstanding` | same | `PENDING` always | n/a, runs no session |
| `forces` | `collect_task` while uncollected and `tries`, else `submit_answer` | same, else `submit_answer_as_file` | `""` | n/a |
| `offers` | today's exclusion logic | same | everything in `turn.offered` | n/a |
| `mechanics` | call the tool, here is the schema | same, with the file contract | work, write your files, idle when done | n/a |
| `instructs` | answer now from what you know | same | there is nothing to force; carry on or idle | n/a |
| `nudges` | answers only arrive through the tool | same | carry on, or idle if there is nothing to do | n/a |

Nothing in the `Standing` column is a stub. `""` and `PENDING` are answers, and they are the answers
that make a standing agent possible: never forced, never halted for having children, and told in its
first paragraph that it does not finish.

`Deterministic`'s column is `n/a` for six rows because it is a `Profile` and not a
`SessionProfile`: those methods are not on the protocol it implements, so there is nothing to stub.
That asymmetry is what the two-protocol split is for.

### Lifecycle tools

```python
wanted = set(role.tools) | set(profile.tools)
```

replacing `wanted = set(spec.role.tools) | {Idle.name}`, which was this list hardcoded for the only
profile that existed. The union is what makes the earlier crash unexpressible: `Answering.forces`
can only name `collect_task` because `Answering.tools` guarantees it is bound.

A role that also lists a lifecycle tool is a mistake and is **not** refused. The union absorbs it
and nothing downstream can tell. Validating it is deferred rather than designed away.

`build_registry`'s `withheld = TERMINAL_TOOLS - {submitting(spec.role.tools)}` is deleted, along
with `submitting()` itself. No inference remains: each profile names one terminal tool, or none.

### Validation moves into the profile

`check_contracts` keeps two faults and loses four:

| fault | where it goes |
|---|---|
| `_contract_fault` — does a `ClassRef` resolve | **stays**: true for every profile |
| `_hook_fault` — hook names a used tool; arity and types resolve | **stays**, with one change below |
| `_submit_fault` | `Answering.faults` / `AnsweringAsFile.faults` / `Standing.faults` |
| `_answer_file_fault` | `AnsweringAsFile.faults` |
| `_content_fault` | `AnsweringAsFile.faults` |
| `_run_fault` | `Deterministic.faults` |

`_submit_fault`'s `if role.run != NO_RUN: return ""` exemption disappears rather than moving. A
deterministic role is not exempted from needing a terminal tool; it has a profile that never
required one.

The one change to a staying fault: `_hook_fault` computes `not_in_role = named - set(role.tools) - {Idle.name}`,
which would refuse a `before` hook on a terminal tool now that the tool comes from the profile. It
becomes `named - set(role.tools) - set(resolve_profile(role.profile).tools)`, and the `{Idle.name}`
special case goes with it — `idle` is a lifecycle tool like any other. `_hook_fault` already receives
the whole `Config`, so it can resolve the profile itself; nothing is stored on the frozen `Role`.

`check_contracts` then runs base faults first and profile faults second, keeping the existing `or`
chaining so one group reports at a time.

### Selection is explicit

```python
# RawRole
profile: RawClassRef

# Role
profile: ClassRef
```

Required in both, no default. `resolve_profile(ref) -> Profile` joins `resolve_class`,
`resolve_run`, `resolve_before` and `resolve_after`, importing the module, instantiating the class
and refusing anything that is not a `Profile`.

```toml
[roles.investigator]
profile = { module = "ancalagon.profiles.answering", name = "Answering" }
behaviour = "..."
tools = ["read_file", "ripgrep", "find_symbol"]
budget = { turns = 14, tool_calls = 35 }
```

Note what left that table: `submit_answer` is no longer in `tools`, because `Answering` brings it.

`Role` holds the `ClassRef`; the resolved instance is passed where it is needed rather than stored
on the frozen model, exactly as `role.answer` is a `ClassRef` and `output_class` is resolved beside
it.

### What stays in the session

`_loop`'s shape, the transcript, metering, the letterbox, budget spending, `_run_tools`' cost rule,
`_uncalled`'s nudge-or-fail branch, `_settled`, `_outcome_of_use`, `_refused` and `_ended`. Those
read a `Reply` or a `ran`, so by the scoping above they are not profile questions.

`Idle.run`'s refusal goes, because availability is now `offers`' answer. `Idle` keeps reading the
bus to populate `Idled.waiting_for` — data for its own result, not a decision — and
`Idled.text_for_model` branches for an empty `waiting_for`, which otherwise reads *"idling until one
of agents [] finishes"*.

## Known debts

**`spawn_by_run` is a second source of truth.** It keys on `role.run` to choose an executor, so a
role could declare `Answering` and still carry a `run` ref and be spawned deterministically.
`Answering.faults` refusing a `run` ref closes the gap by validation rather than by construction,
which is weaker than making it unexpressible. Moving the choice to the profile is the right fix and
is out of scope here.

**`watcher_in` stays keyed on `run == WATCH_FOR`.** That asks "is there a watcher in this config",
which is finer-grained than "what kind of role is this", so a profile cannot answer it. Left alone
deliberately.

**`af0dcde`'s guard becomes dead and must be removed in the same change.** `_forced` checks
`COLLECT in self.registry.names()`; once `Answering.tools` guarantees `collect_task`, that check is
permanently true. Leaving it in would assert a possibility the design has removed.

**A role listing a lifecycle tool is silently absorbed.** Stated above; deferred by decision, not
oversight.

**Writing a profile is writing policy, not configuration.** A badly written one can offer no tools,
force a tool it never declared, or return prose that tells an agent to do something impossible, and
nothing validates prose. This is the same exposure `before`, `after` and `run` already carry, one
grain larger.

## Testing

1. **`tests/unit/test_turn.py`, one behaviour.** `Turn` is built from a session's state and `final`
   tracks `remaining` rather than being settable: a `Turn` with turns left is not final, one with
   none is, and there is no way to construct a disagreeing pair.
2. **`tests/unit/test_profiles.py`, one behaviour per profile, four tests.** For each, a `Turn`
   constructed by hand and every method asserted against concrete values — `Answering.forces`
   returning `collect_task` with an uncollected child and `submit_answer` without one;
   `Standing.forces` returning `""` and `Standing.halts` returning `PENDING` with outstanding
   children; `Deterministic.faults` refusing a missing `run`. No `FakeLLM` needed anywhere, because
   nothing in the protocol touches a model.
3. **`tests/unit/test_session_loop.py` extends rather than gains a sibling.** Its existing
   assertions on offered tools and forced names must pass **unchanged** once `Answering` is wired
   in. That is the proof the refactor preserves behaviour, and it is the reason commits 1 and 2
   below are separate from commit 5.
4. **`tests/unit/test_hooks.py` extends** for `_hook_fault` consulting `profile.tools`: a `before`
   hook on `submit_answer` resolves for an `Answering` role that does not list it in `tools`, and is
   refused for a `Standing` role, which has no such tool.
5. **`tests/unit/test_config_load.py` extends**: a role with no `profile` is refused; a `profile`
   naming a class that is not a `Profile` is refused with a message naming the class; the four
   shipped profiles all resolve.
6. **`tests/integration`**, whole suite, not the files these changes are about. Forty seconds, and
   two plans in a row let a regression through by narrowing it.
7. **Mutation-check every new test.** Make `Answering.forces` always return its terminal tool; make
   `offers` return `turn.offered` unfiltered; make `faults` always return `""`; make `Turn.final`
   a stored field set to `False`. Each must fail a named test.

## Commits

Five. The first two change no behaviour, which is what makes the rest reviewable.

1. **`Turn`, and the session computing it.** The decision methods keep their current bodies and read
   their inputs from `Turn` instead of from parameters and `self`. No protocol, no profiles, no
   config change. Every existing test passes untouched; if one does not, the refactor is wrong.
2. **`Profile`, `Answering`, `AnsweringAsFile`, `resolve_profile`, and `profile` on the role.** The
   session delegates the six `SessionProfile` decisions. `Answering` encodes exactly today's policy, so
   behaviour is identical and `test_session_loop.py`'s assertions stand unchanged. Configs and test
   configs gain `profile` and lose their terminal tool from `tools`. This is the big mechanical
   commit and it is the one to review hardest.
3. **Validation moves.** `faults` on each profile, the four fault functions deleted, `submitting()`
   and `build_registry`'s `withheld` deleted, `_hook_fault` consulting `profile.tools`, `af0dcde`'s
   now-dead guard removed. Error messages change; the tests say how.
4. **`Deterministic`.** `_run_fault` becomes its `faults`, and `spawn_by_run`'s debt is recorded in
   `docs/architecture.md` rather than fixed.
5. **`Standing`.** The new capability, `Idle.run`'s refusal removed, `Idled.text_for_model`'s
   branch, and a standing role in a config with an integration test. Everything before this commit
   is a refactor; this is the one that adds something.

Commit 1 lands alone, and commit 2 lands alone. Together they touch `session.py`, `session_for.py`,
`check_contracts.py`, the config layer, four shipped configs and a dozen test files while changing
nothing a user can observe — and that property is only checkable if nothing else is in the diff.
