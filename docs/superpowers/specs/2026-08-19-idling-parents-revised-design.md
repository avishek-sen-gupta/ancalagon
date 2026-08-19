# Idling parents, revised — design

Supersedes `2026-08-17-idling-parents-design.md`. Tasks 1-4 of its plan are committed; this
revises what remains and corrects two bugs in what landed.

## Why revise

The first design fired a wake when a child finished. Building it exposed two defects in the
committed code and one in the design, all of the same kind: **a question about a task was being
asked of an agent, or of a single event.**

**Bug 1, Critical, committed.** `live_children` filters `t.parent_agent = ?` on one agent id, but
`enqueue` writes `parent_agent` only when the task row is new. So a resumed parent cannot see
children created by its earlier attempt. Reproduced:

```
attempt 1 of root = 1   children = [2, 3]
attempt 2 of root = 4
live_children(attempt 2) = []      <- agent 3 is still live
```

`build_registry` therefore withholds `idle` and offers `submit_answer` to a woken parent whose
children are still running — the exact invariant the feature exists to enforce, broken on the only
attempt the feature produces. Task 3's tests passed because they exercise attempt one only.

**Bug 2, Critical, committed.** A worker records its own account and the supervisor appends
`exited` over it, so by latest status an idled agent and a completed one are the same row:

```
idled agent  latest status: exited
completed    latest status: exited
distinguishable by latest status? False
```

Every consumer that asks "what happened to this agent" by reading the last row is wrong. That
includes `live_children` and `active_for`.

**The design defect.** An event fired at `_finish` puts correctness in six places — four callers
plus two exit paths — and one caller, `shutdown`, means "we are giving up" rather than "this
finished". Wakes hung there enqueue work nobody drains.

## The one primitive

Every parent-facing question reduces to one, asked of a **task**:

```
outstanding(T):   N = newest agent of T          -- MAX(agents.id) WHERE task = T
    N's latest status in (queued, claimed, running)   -- an attempt is running
    OR  'idling' in history(N)                        -- stopped, awaiting a wake
settled(T) = not outstanding(T)
```

Reading history rather than the last row is what Bug 2 requires. An agent idles at most once,
because idling ends the attempt, so "contains idling" is unambiguous for one agent.

`TERMINAL` is unchanged and keeps its current meaning: the *attempt* ended, nothing to reap. It
stays the supervisor's instrument for process scheduling and is not used for any question about
a task.

## Children resolve through the task

```
children(T) = tasks whose parent_agent is any agent of T
```

`parent_agent` names whichever attempt happened to create the child; the edge means task to task.
Resolving through every agent of the parent's task fixes Bug 1 and makes the frozen column stop
mattering. `live_children` is rewritten on this and keeps its signature, since callers hold an
agent id.

## Consumption is recorded

`collect_task` appends a `collected` event to the child's newest agent when that child is settled.
Consumption becomes a fact in the log instead of something inferred.

This is what lets a parent be held to account. Withholding `submit_answer` while children run only
prevents finishing *during* their work; a parent could still wake, read nothing, and answer. With
`collected` recorded, it cannot.

## Narrowing moves into the loop, behind a port

Today `build_registry` decides once per attempt which of `idle` and `submit_answer` an agent gets.
That cannot survive collection, because the state changes mid-attempt: a parent that collects its
last child would hold neither tool — `submit_answer` withheld at attempt start, `idle` refusing
with nothing outstanding — and would burn turns to a deadlock.

So narrowing becomes per turn, and the session learns the facts through an injected port, exactly
as it already learns metering through `Meter`:

```python
class Children(typing.Protocol):
    def outstanding(self) -> tuple[int, ...]: ...
    def uncollected(self) -> tuple[int, ...]: ...
```

`BusChildren(bus, agent)` implements it; `NoChildren` is the null object for an agent that cannot
delegate. Each turn the session declares:

- `idle` when `outstanding()` is non-empty
- `submit_answer` when both are empty, **or** this is the final turn

`build_registry` stops choosing between them and binds whatever the role allows. The `exempt` /
`excluded` logic added in Task 3 is deleted.

## `_final_turn` collapses into the loop

`_final_turn` is special three ways: it is a turn beyond the budget, it ignores the registry's
declarations and passes its own, and it is the only caller of `force_tool`. That specialness is
why Task 4 exists at all — a second code path had to be taught what the loop already knew.

With narrowing per turn, the last turn is an ordinary turn with two flags: it records
`FINAL_INSTRUCTION`, and it declares and forces `submit_answer`. Outcome parsing moves after the
loop. `Session.run` has one path.

The final turn's `submit_answer` is offered regardless of collection. Being cut off is not the
same as choosing to skip, and the outcome is `Exhausted` either way.

## The wake predicate

Evaluated by the supervisor each tick, not fired by any caller:

```
wakeable = tasks T where
    'idling' in history(newest agent N of T), at event id E
    AND some C in children(T):  settled(C)
                                AND C's newest agent has an event with id > E
```

`agent_events.id` is `INTEGER PRIMARY KEY AUTOINCREMENT`, a total order over the run. `> E` means
*settled since I last stopped*: a child that settled before the parent idled was already visible
to it, and waking for it again is what makes a re-idled parent spin.

Idempotence is structural. Once T is re-enqueued its newest agent is the new one, whose history
holds no idling, so T leaves the result set. Two children settling in one tick yield one row,
because the query is per task. There is no counter and no flag.

Added to `tick()` as `_start_queued(); _reap(); _wake_idling()`. No existing step moves, and
because the wake runs at the end of the tick, `run_until_idle`'s existing `queued_count() == 0`
check sees it on the next line. **`run_until_idle` does not change.**

`shutdown()` wakes nothing — not because it is suppressed, but because it does not schedule.

## Why it terminates

Both routes into `Idling` require an outstanding child:

- the `idle` tool refuses when `outstanding()` is empty,
- exhaustion returns `Idling` only when `outstanding()` is non-empty, and answers otherwise.

An outstanding child eventually settles, and its settling event necessarily has an id greater than
the idling event that preceded it. So **every idling parent has guaranteed future news**: no idle
can strand.

Nor can it livelock. Each wake is caused by a distinct child settling after the parent's most
recent idle; children are finite and depth is bounded, so wakes are bounded. A parent that never
collects still terminates — when nothing is outstanding, exhaustion answers rather than idling.

## What this deletes

`resumable_idle` and `latest_agent` were built for the event-driven design and have no caller
here. Task 3's `exempt` / `excluded` narrowing goes with `build_registry`'s choice. `_final_turn`
goes with the collapse. The revision is net-negative code.

## What this does not do

**It does not bound total budget per task.** A woken parent gets its role's budget afresh, as any
resumed agent already does. A parent with three children may consume four budgets.

**It does not drain the queue on the orphans path.** `run_until_idle` still returns past queued
work when it finds agents the database calls in-flight with no live process. That is a corruption
report, and this design does not change what it means.

**It does not stop a parent ignoring a result it has collected.** `collected` records that the
parent read the answer, not that it used it.

**It does not cache the conversation.** Each wake re-sends the transcript once. Three wakes for
three children instead of sixteen polls is the win; making each wake cheaper is a change to
`_system_blocks`' cache breakpoint.
