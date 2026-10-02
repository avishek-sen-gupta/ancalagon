# An agent that never answers

## The problem

Every role that runs a session must answer. Three separate gates enforce it, and together they
make a long-lived collaborator inexpressible.

1. **`check_contracts._submit_fault`** refuses at startup any role that runs a session and names
   neither `submit_answer` nor `submit_answer_as_file`: *"a role that runs a session must name one
   of [...]"*. The only exemption is `role.run != NO_RUN` — a deterministic role, which runs no
   session at all.
2. **`Idle.run`** refuses when `live_children(snapshot, agent)` is empty: *"nothing to wait for: no
   live children"*. So the bottom-most agent in a tree — the one with no children of its own — has
   no way to end an attempt except by answering.
3. **`idle` is not declarable.** `build_registry` does `wanted = set(spec.role.tools) | {Idle.name}`,
   binding it into every registry whether the role asked or not, and `Session._declarations`
   withholds it per turn with `{IDLE} if not outstanding`. Whether an agent may sleep is therefore
   the harness's decision twice over, and a role that never mentioned `idle` is nonetheless offered
   it the moment it has a live child.

An agent that is given no terminal tool, may sleep when it chooses, and communicates by leaving
notes is a different kind of thing: a standing collaborator that edits files it owns, is woken when
something arrives for it, and never produces a final value. Nothing about the loop prevents this.
Only those three gates do.

**Quiescence already works, and this spec adds nothing to it.** When every agent has idled its
process has exited, so `Supervisor.live` is empty; `has_news` asks `is_news`, which for a `Closed`
attempt is `verdict is not AgentStatus.IDLING`, so an idling child is explicitly **not** news and
nobody is spuriously woken; `wakeable` therefore comes back empty, `queued_count()` is zero, and
`_idle_step` returns `False`. `run_until_idle` returns and `_outcome_of` reports the root's last
outcome. The whole tree sleeps and the run ends, today, with no new state, status or table.

## What this is not

**Not agent-to-agent notes.** The letterbox stays what it is: `FileLetterbox` reading
`task_dir/notes/*.txt`, filled only by `ancalagon note`, delivered by `_deliver()` at the top of a
pass. Typed notes, task-addressed notes, and a note that enqueues its recipient are a separate
change whose contract is undecided. Until it lands, a slept leaf is revived the way anything else
is — by `answer_task`, or by re-running `run`, which enqueues the root unconditionally.

**Not compaction.** A persistent agent with `turns = "infinite"` grows its transcript without bound,
which is `2026-10-03-a-checkpoint-the-agent-cannot-skip-design.md`. That spec is a prerequisite for
using persistent agents in earnest, not a part of this one. Nothing here depends on it and nothing
here blocks it.

**Not a bound on wakes.** Two agents that wake each other indefinitely would keep a run from ever
quiescing. Deliberately out of scope: when a run should stop is the business of whatever drives it,
not of the supervisor.

**Not a change to `watch_file` or `watch_for`.** A watcher blocks in
`while ctx.fs.changed_at(watched) <= request.since: ctx.clock.sleep(...)`, so it holds a live process
and prevents quiescence for as long as it waits. That is what it is for and it stays. A persistent
agent simply should not wait that way.

**Not a new status.** `Idling` already means "this attempt stopped and may resume". A standing agent
produces exactly that, repeatedly, and nothing downstream needs to tell the two apart.

## Design

### `idle` becomes an ordinary declarable tool

Three deletions, no additions:

```python
# session_for.build_registry
wanted = set(spec.role.tools)                      # was: | {Idle.name}

# Session._declarations
excluded: set[str] = {self.submit} if outstanding or uncollected else set[str]()
                                                   # was: ({IDLE} if not outstanding else ...) | (...)

# check_contracts._hook_fault
not_in_role = named - set(role.tools)              # was: - {Idle.name}
```

The third exists only to paper over the first: because `idle` was bound without being declared, a
hook naming it had to be exempted from the "names a hook for a tool it does not use" check. Remove
the injection and the exemption is dead weight. `IDLE` in `session.py` goes with it.

This is the whole of "a pure consumer decision": a role that wants to sleep names `idle`, and is
offered it on every turn thereafter. The harness stops having an opinion.

**Every shipped config gains it**, because none of them names it today and all four rely on the
injection: `ancalagon.toml` `[roles.root]`, `ancalagon.example.toml` `[roles.root]`, `research.toml`
`[roles.root]`, and `blackboard.toml` both `[roles.root]` and `[roles.analyst]` — the last being the
one whose behaviour already says *"call watch_file on the blackboard and then idle"*.

Forgetting it degrades rather than breaks, which is what makes handing this over safe. `_loop` still
has `if final and outstanding: return Idling(...)`, so a role that delegates but never declared
`idle` still ends up idling when its turns run out. It simply burns its whole budget on text first
and then wakes with a fresh one. Wasteful, not wedged.

### A leaf may sleep

`Idle.run`'s refusal goes. It was never protecting against a model mistake: `BusChildren.outstanding()`
and `Idle.run` both call `live_children(snapshot, self.agent)`, and `_declarations` withheld `idle`
whenever that was empty — so the only reachable case was the last live child settling *between* the
top of the turn and the tool call. A time-of-check/time-of-use guard, and with `idle` declarable the
session no longer consults that value at all.

`NoIdle` stays exactly as it is. A session with no bus is a different refusal with a different
message, and it remains correct.

One consequence needs handling rather than inheriting. `Idled.text_for_model` is
`f"idling until one of agents {list(self.waiting_for)} finishes"`, which for an empty `waiting_for`
reads *"idling until one of agents [] finishes"*. It branches:

```python
def text_for_model(self) -> str:
    if not self.waiting_for:
        return "idling until something arrives"
    return f"idling until one of agents {list(self.waiting_for)} finishes"
```

`seen_through` is still the measured watermark, so a leaf that acquires children later is woken by
the existing path without a special case.

### A role may name no submit tool

`_submit_fault` is deleted. Its job is taken over by the absence itself: **a role that names no
terminal tool is declaring that it never answers.** Nothing needs to know which role is the root —
`_submit_fault` could not have known anyway, since it receives `(name, role)` and the root is
`config.run.role`.

`submitting` must be able to say "none", which it currently cannot:

```python
NO_SUBMIT = ""

def submitting(tools: collections.abc.Sequence[str]) -> str:
    if SubmitAnswerAsFile.name in tools:
        return SubmitAnswerAsFile.name
    if SubmitAnswer.name in tools:
        return SubmitAnswer.name
    return NO_SUBMIT
```

A string sentinel rather than a null object, following `NO_LIMIT = "infinite"`: the value is a
registry key, and every consumer already treats it as one.

Six sites read `self.submit`. With `turns = "infinite"` — the only budget a standing agent has any
business carrying — two are unreachable, because `Infinite.exhausted` is always `False` so `final` is
never true: `_forced` and `_final_instruction`. A third, `_declarations`' non-final
`{self.submit} if outstanding or uncollected`, excludes `NO_SUBMIT` from a registry that never held
it, which is a no-op. So exactly two need a branch, and both are text that would otherwise instruct
an agent to call a tool it does not have:

- `_system().static` — see below.
- `_continue_instruction` — both arms name the submit tool. For `NO_SUBMIT` they become
  *"Noted. Carry on."* and *"Keep working, or idle if there is nothing to do."*

A finite budget together with no submit tool is a misconfiguration and is left to fail. `_forced`
would return `NO_SUBMIT`, `_declarations` would call `registry.get("")`, and `Session.run`'s handler
would report `Failed` with the `KeyError`'s traceback. Not silent, not a hang, and not worth
engineering around: a standing agent's turns are infinite by definition.

### A role declaring an answer nobody collects is refused

`_answer_file_fault` already refuses a role that declares `answer_file` without naming
`submit_answer_as_file`, because *"nothing checks it"*. A role declaring `answer` with no terminal
tool at all has the same defect — `output_class` resolves it, `_system` renders its JSON schema into
the prompt, and nothing will ever validate anything against it. One more fault in the same style,
with the same wording.

This is what keeps the deletion of `_submit_fault` from being a loss of checking: the startup check
moves from "you must answer" to "do not declare an answer you cannot give".

### What a standing agent is told instead

`_system().static` is `role.behaviour` followed by harness-appended mechanics. The split stays —
the role says what the agent is **for**, the harness says how the machinery **works** — and only the
appended half changes:

```python
def _mechanics(self) -> str:
    if self.submit == NO_SUBMIT:
        return (
            "You do not answer and you do not finish. You work, you write what you have "
            "to the files you own, and when there is nothing left to do you call idle. "
            "Idling ends this turn; you will be started again when something arrives for "
            "you, with this conversation intact."
        )
    schema = self.output_class.model_json_schema(schema_generator=Inlined)
    return (
        f"When you have the answer, call the {self.submit} tool with it. That tool is the "
        f"only way to answer; a reply without it is taken as more work to do. Your answer "
        f"must match this schema: {schema}"
    )
```

It stays in `static` rather than `per_item` for a concrete reason: `_system_blocks` puts
`cache_control: {"type": "ephemeral"}` on the static block only, so text that does not vary per turn
belongs there or it is re-sent on every call.

The `per_item` half is untouched. A standing agent still has a goal, an input and its scopes.

## Known debts

**A slept leaf has nothing to wake it until notes enqueue.** `_wake_idling` enqueues only
`wakeable` tasks, and `has_news` is entirely about children settling, so nothing routes a note to a
sleeping agent. Until the notes change lands, a leaf that idles stays asleep for the rest of the run
and is revived only by `answer_task` or by re-running `run`. This is a real gap and it is accepted
deliberately: the gates come out first, the delivery mechanism follows, and the two are separately
reviewable.

**`Idling` carries neither a value nor an error.** A one-shot role that declares `idle` and sleeps
instead of answering therefore leaves a child that is permanently live, a parent that idles too, and
a run that goes quiet having produced nothing — no failure, no answer, no complaint. That is the
bungle this spec hands to the config author, and it is the one worth being able to diagnose.
`ancalagon trace` already shows it; nothing warns about it.

## Testing

1. **`tests/unit/test_tools.py::test_idle_refuses_once_its_children_have_settled` reverses.** This
   is a deliberate inversion of an existing assertion, not a weakening: the behaviour it pins is the
   behaviour being removed. It becomes a test that an agent with no live children idles, returning
   `Idled(waiting_for=())`, and that `text_for_model` reads *"idling until something arrives"*. The
   no-bus half of `test_check_task_collect_task_and_idle_refuse_cleanly_when_there_is_no_bus` is
   untouched, since `NoIdle` is unchanged.
2. **Five registry assertions lose their uninvited `idle`** — `test_hooks.py:217`,
   `test_answer_file.py:69`, `test_tools.py:410` and `:439`, and the list in `test_watch.py:240`.
   Each is a role that never declared it. Changing them *is* the test of the first commit.
3. **`tests/unit/test_config_load.py` extends** for the contract changes: a role naming no terminal
   tool now loads, and a role declaring `answer` with no terminal tool is refused with a message
   naming the role and the field.
4. **`tests/unit/test_session_loop.py`, one behaviour.** A role with `turns = "infinite"`, no submit
   tool and `idle` declared: the system prompt's static half contains the standing-agent mechanics
   and neither the submit instruction nor an answer schema; a reply calling no tool is answered with
   *"Noted. Carry on."* rather than an instruction to submit; and a reply calling `idle` ends the
   attempt `Idling`. Concrete strings, not substring checks on the word "idle".
5. **`tests/integration`**, whole suite, not the one file this is about — it takes about forty
   seconds and two plans in a row let a regression through by narrowing it. A standing role declared
   in a test config plus a root that delegates to it, run to quiescence: `run` returns, the root's
   outcome is `Idling`, and the standing agent's task has at least two attempts.
6. **Mutation-check every new test.** Restore `Idle.run`'s refusal; restore the `| {Idle.name}`
   injection; make `_mechanics` return the answering text unconditionally. Each must fail a named
   test.

## Commits

Four, in this order.

1. **`idle` becomes declarable.** The three deletions, `IDLE` removed from `session.py`, and the four
   shipped configs updated. No new capability — a role that declares `idle` behaves exactly as it
   does now, and one that does not loses a tool it never asked for. The five test assertions change
   here, which is what makes the commit self-evidencing. `README.md`'s per-turn offering table is
   reworded: its first two rows name `idle` as something the session grants or withholds, and it
   becomes a tool the role declares instead.
2. **A leaf may sleep.** `Idle.run`'s refusal and `Idled.text_for_model`'s branch. Separately
   revertible, and the only commit that changes what a tool does rather than who may call it.
3. **A role may name no submit tool.** `NO_SUBMIT`, `submitting`'s third case, `_submit_fault`
   deleted, the new answer fault, `_mechanics`, and `_continue_instruction`'s branch. This is the one
   with the prose in it, and the one whose review is about what a standing agent is told.
4. **A standing role in the examples.** One added to `blackboard.toml`, or a new example config, plus
   the integration test and the `README.md` section describing the kind of agent this makes possible.
   The mechanism works without it; this is the commit that makes it discoverable.

Commit 1 lands alone. It touches five test files and four configs while changing no behaviour that
any role asked for, and bundling it with commit 2 would make a reviewer unable to tell a withdrawn
tool from a relaxed guard.
