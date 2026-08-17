# Waiting parents — design

## Why

A parent that delegates has no way to wait. `check_task` reads one row from the bus and
returns immediately, so a parent with live children can only ask again, and asking again costs
a model call carrying the whole conversation.

Run `ws/runs/r_0004` measures it. The root spent 276,770 input tokens across 26 calls;
**148,851 of them — 53% — were calls 3 through 18, which did nothing but ask whether three
children had finished.** Forty-nine `check_task` calls over sixteen rounds, input growing about
363 tokens a round, output a flat 125 each time. The root exhausted its 25 turns and was forced
to answer mid-investigation, having spent 16 of its 70 tool calls.

`check_task` costs 0 against the tool-call budget, which prices the tool correctly and prices
the round trip at zero. Turns are the currency a polling parent actually spends, and nothing
charges against them until they are gone.

Prompt caching does not soften it: `cache_read` is exactly 3,157 on all 26 calls — the static
system prompt — while input climbs from 4,531 to 16,578. The conversation, which is the part
that grows, is never cached, so every poll re-sent the whole transcript at full price. Caching
it would cut the tokens and leave the turns. A parent that is not running has no transcript to
re-send, which is why this design stops the parent rather than making its polling cheaper.

## What a waiting parent is

A parent that stops is **not blocked**. Its process exits; its state is on disk; the supervisor
re-spawns it when something happens. That is already how `NeedsInput` works: a worker writes
`outcome.json`, records its status, and exits; `answer_task` appends to `transcript.jsonl` and
re-enqueues; `enqueue` reuses the task row and adds a new agent; the new worker rebuilds the
session from `repair(load(transcript_path))`. An integration test asserts a real provider
accepts that resumed transcript.

Staying alive and watching the bus in-process was rejected. It resumes without re-sending the
transcript, but the parent holds a concurrency slot and an OS process for the whole wait, so
with `max_concurrent_agents = 4` three waiting parents leave one slot for every child in the
tree — a deadlock that appears exactly when the harness does what it is for, and surfaces as a
timeout rather than as an error that explains itself. It also loses its state to a supervisor
crash, where disk would have kept it.

Because a waiting parent is suspended rather than blocked, anything that appends to the bus can
wake it. A human-in-the-loop hook needs no new pathway.

## The invariant

**`submit_answer` is not offered while an agent has live children.** Not an error the parent
must handle — the tool is absent, the same way `build_registry` already drops `delegate_*` at
`max_depth`. A parent cannot finish without accounting for the work it commissioned, and
cannot accidentally abandon it.

This removes a capability: today a parent may decide a child's answer no longer matters and
answer without it. That is deliberate. In `r_0004` the failure was not that the root could
abandon children but that nothing recorded it had.

Every other tool stays available. The parent reads files, delegates more children, and thinks
for as long as its budget allows.

## `idle`

A reply with no tool calls already means "here is my final answer" — `session.py` validates
that text against the output contract and completes. So a parent needs a distinct way to say
"I have nothing more to do until something changes", and that is a tool.

`idle` takes no arguments. Nothing is named because the wake condition is derived from what the
bus already holds: `tasks.parent_agent` records which agent spawned each task, written at
enqueue time and already used by `depth_of` to enforce `max_depth`. There are no ids for a model
to get wrong.

`idle` called with no live children returns a failure — "nothing to wait for" — rather than
stopping. A run must not be able to sleep with everything idle.

## Waking

**A parked parent wakes on every child completion**, not when the last one lands. A parent
reacting to results one at a time is the ordinary case, and the granular rule is the one that
supports it: the parent collects each child as it arrives, acts, and idles again.

The cost is that a parent which only cares once all children are in wakes for each of them and
has nothing to say on the earlier wakes. That is two cheap turns per fan-out against sixteen
polls, and narrowing it later — waking only when no child is live — is a change to the wake
condition alone, with no effect on the tool or the outcome kind. Wake granularity is the thing
this design deliberately leaves easy to change.

## Exhaustion

`_final_turn` forces `submit_answer` when the budget runs out, and `registry.get(SUBMIT)` raises
if the tool is absent — which the invariant guarantees while children are live. So exhaustion
becomes an idle: **a parent that runs out of turns with live children stops instead of taking
its forced final turn.**

It wakes with a full budget. `Session.__init__` sets `self.remaining = spec.role.budget`, and a
resumed worker re-reads an unchanged `spec.json`, so every attempt is granted the role's budget
afresh — the transcript carries over, the budget does not. This is already true of any agent
resumed after `NeedsInput`; it is not introduced here.

Say the consequence plainly: **a role's `budget` is a per-attempt allowance, not a per-task
one.** A parent with three children may consume four full budgets across four attempts. Roles
made budgets authoritative, and this makes authoritative mean per wake. For a fan-out parent
that is the useful reading, but it is a bill someone pays.

It terminates. Children are finite, so wakes are bounded by their number; after the last one no
child is live, `submit_answer` is offered again, and the ordinary exhaustion path applies.

## What changes

**A new outcome kind and status.** A parked parent asked no question, so `NeedsInput` is the
wrong shape. `Waiting` joins `OutcomeKind`, `AgentStatus`, `TERMINAL`, and the `status` CHECK
constraint in the schema — which means a numbered migration, since a shipped migration is never
edited. `check_task` on a parked parent then reports what is true.

**`build_registry`** filters `submit_answer` out when the agent has live children, and gains
`idle` when it has them.

**`Session.run`** returns `Waiting` when `idle` is called, and when turns are exhausted with
live children.

**The supervisor** re-enqueues a `Waiting` agent's task when a child of that agent reaches a
terminal status. The edge is `tasks.parent_agent`; the resume path is `enqueue`, which already
reuses a task row and adds an agent.

## What this does not do

**It does not cache the conversation.** The 3,157-token static prefix is still the only cached
part, so each wake re-sends the transcript once. Three wakes for three children instead of
sixteen polls is the win; making each wake cheaper is a separate change to
`_system_blocks`' cache breakpoint.

**It does not let a parent abandon a child.** Deliberate, per the invariant. If a run needs it,
it needs its own way to be said, and a way to be seen afterwards.

**It does not bound total budget per task.** See Exhaustion.

**It does not change `check_task` or `collect_task`.** Polling remains possible and remains
free against tool calls. This design removes the reason to poll, not the ability.
