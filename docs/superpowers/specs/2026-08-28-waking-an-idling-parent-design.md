# An idling parent wakes on what it had not yet seen

A parent that idles waiting for a child is woken by `Supervisor._wake_idling`, which asks
`has_news` whether any child settled after the parent idled. The comparison is against the wrong
instant, and a child that finishes at the wrong moment is invisible. The parent then waits
forever, silently.

This is not specific to deterministic agents. It was found while designing one, but nothing in
the reproduction below involves a run function.

## The bug, reproduced

Two runs of the same supervisor over the same events, differing only in which process is reaped
first:

| reap order | parent woken | end state |
|---|---|---|
| parent, then child | yes | resumed, run continues |
| child, then parent | **no** | `IDLING`, queue empty, `run_until_idle` returns normally |

`has_news` requires a child's newest event id to be greater than the parent's `IDLING` event id:

```python
idled_at = max(idled)
return any(
    is_news(snapshot, newest_agent(snapshot, child.id))
    and max(e.id for e in snapshot.events[newest_agent(snapshot, child.id)]) > idled_at
    for child in snapshot.tasks
    if child.parent_agent in snapshot.agents_by_task[task]
)
```

The parent's `IDLING` event is not written when the parent decides to idle. It is written when
the supervisor **reaps** the parent, in `_close`. Between those two moments the parent finishes
its turn, writes its transcript, writes `outcome-<agent>.json`, and exits. A child that settles
anywhere in that window has all of its events written first, so its newest event id is *lower*
than `idled_at` and it can never wake anyone.

For a model-driven agent that window is a whole turn. `Idle`'s own guard does not help: it checks
`live_children` at call time, and the entire race happens afterwards.

The failure is silent — no crash, no timeout, no error. `run_until_idle` returns with the parent
parked at `IDLING` and the child's answer never collected.

## What the comparison is actually for

`is_news` is already "settled and not yet collected": it returns True for `Closed` with a verdict
other than `IDLING`, and for `Lost`, and False for `Collected`. So the `> idled_at` clause is not
doing the unseen-ness work. It does exactly one job — it stops a **stale child** (one that had
already finished, uncollected, before the parent idled) from waking the parent.

Deleting the clause was considered and is wrong. With a stale child and a live child, `Idle`
succeeds because the live child is outstanding, so the parent legitimately idles; the stale child
is still `is_news`, so the parent is woken immediately, idles again, and spins for as long as the
live child runs. Verified against a constructed snapshot: `live_children` returns the live child
only, `is_news` on the stale child is True, and `has_news` today is correctly False.

So the clause stays. The instant it compares against is what moves.

## The fix

The parent records how much of the event log it had seen when it decided to idle, and `has_news`
compares against that instead of against the reap-time event id.

```python
def has_news(snapshot: Snapshot, task: int) -> bool:
    match [e for e in snapshot.events[newest_agent(snapshot, task)] if e.status is AgentStatus.IDLING]:
        case []:
            return False
        case [idled, *_]:
            return any(
                is_news(snapshot, newest_agent(snapshot, child.id))
                and max(e.id for e in snapshot.events[newest_agent(snapshot, child.id)])
                > idled.seen_through
                for child in snapshot.tasks
                if child.parent_agent in snapshot.agents_by_task[task]
            )
```

Two things change and nothing else. `idled` stops being `max()` of a list of ids and becomes the
event itself — an agent produces exactly one outcome, so it has at most one `IDLING` event and
there is nothing to take a maximum over. And the right-hand side of the comparison becomes that
event's watermark instead of its own id.

The watermark is the largest event id anywhere in the snapshot at the moment `idle` runs — across
every agent, not just the parent's children, because it means "how much of the log I had seen".
`idle` already takes that snapshot to call `live_children(snapshot, agent)`, so reading it costs
nothing.

Four cases, all of which this settles:

| case | behaviour |
|---|---|
| child settles after the parent decides, before the parent is reaped | its events are above the watermark — **wakes**, which is the bug fixed |
| stale child, finished and uncollected before the parent idled | its events are below the watermark — does not wake |
| parent wakes, does not collect the stale child, idles again | the new watermark is higher still — does not wake, so no spin |
| child is itself a parent that idles and is later woken | it returns as a new agent whose events are above the watermark — wakes |

The last row is why the watermark is an **event id and not a set of awaited agents**. Recording
`Idled.waiting_for` was the first design and it has a trap: those are agent ids, and a child that
idles and is woken comes back as a *new* agent on the same task, so the recorded id names an
attempt that is `Closed(IDLING)` forever and its parent never wakes. A set would have to be
mapped through `task_of` at every check. A watermark names nobody and so cannot go stale.

It is also why the watermark is an event id and not a timestamp. `agent_events.ts` exists on
every event, but it is stamped when the supervisor records the event — the same wrong instant —
and it is not a safe ordering key regardless: `FakeClock` only advances when slept, so a batch of
events written in one tick share an identical timestamp and `>` is false between them. Event ids
are `INTEGER PRIMARY KEY AUTOINCREMENT`, unique and monotonic by construction.

## Where the number travels

```
Idle.run          reads max event id from the snapshot it already took
  -> Idled        gains seen_through: int, beside the waiting_for it already carries
  -> Session      passes it through instead of discarding it (session.py:228)
  -> Idling       gains seen_through: int
  -> outcome-<agent>.json
  -> Supervisor._close reads it from the outcome and passes it to bus.record
  -> agent_events.seen_through
  -> has_news
```

`OutcomeHeader` is what `_close` parses, so it gains `seen_through: int = 0` — every other
outcome kind leaves it at zero, and only an `IDLING` event ever carries a meaningful value.

`bus.record` and `_record` gain a `seen_through: int = 0` parameter, alongside the `pid` and
`summary` they already take for the same reason: a field that only some events use.

Migration `002` adds one column:

```sql
ALTER TABLE agent_events ADD COLUMN seen_through INTEGER NOT NULL DEFAULT 0;
```

with the matching `002_*.down.sql`. `AgentEvent` gains `seen_through: int = 0`.

`ts` is not touched. A worker-decided verdict's timestamp reports when the supervisor observed
it, which is what `AgentEvent` says it is — "one observation about an agent". The genuinely
misleading part is that such an event records `source=SUPERVISOR` for a decision the worker made,
and that is a separate question from this bug. Changing `ts` to decision time would give one
column two meanings and let `trace/graph_of.py` and `viz/mermaid.py`, which both order by `ts`,
render a timeline that runs backwards.

## Deterministic agents

A run function may return `Idling` and nothing checks that it has anything to wait for. Its
watermark would be whatever it read, and a run function that idles with no outstanding child
never wakes — the same stall this spec removes for sessions, from a different cause.

`Idle`'s refusal is what protects a session, and the equivalent for a run function is one call to
`live_children(snapshot, ctx.agent_id)` before returning `Idling`. That is not in this spec: no
run function idles today, and the guard has no caller until one does. It is named here so the
first one that idles does not rediscover it.

## Units

1. **Carry the watermark.** `Idled.seen_through`, `Idling.seen_through`, `OutcomeHeader`,
   `AgentEvent`, `bus.record`/`_record`, migration `002`, and `Idle.run` reading it. `has_news`
   still compares `idled_at`, so nothing changes behaviour yet and the suite proves it.
2. **Compare against it.** `has_news` switches to `seen_through` and drops `max(idled)`. This is
   the commit that fixes the bug, and it is three lines.

Unit 1 is inert on its own, which is the point: the column and the plumbing land under a green
suite before the scheduling rule changes.

## Testing

The reproduction is the regression test, and it belongs in `tests/unit/test_supervisor.py`
beside `test_a_tick_wakes_an_idling_parent_once_a_supervisor_has_reaped_its_child`, which already
covers the ordering that works today.

- **Both reap orders wake the parent.** One test, parameterised by which process is marked done
  first, asserting a new agent is queued against the parent's task in each. Reversed order fails
  before unit 2 and passes after — that is the mutation check, and it comes for free.
- **A stale child does not wake the parent.** A first child settles and is left uncollected, a
  second child runs, the parent idles. Assert `has_news` is False, and that it becomes True only
  when the second child settles. This is the case that rules out deleting the clause, and without
  it a later reader will delete it again.
- **A woken child wakes its own parent.** Three levels: the middle agent idles, is woken, and
  completes as a new agent. Assert the top parent wakes. This is what the discarded
  `waiting_for` design would have broken.
- **The watermark survives the round trip.** `Idle` writes it, the outcome carries it, `_close`
  records it, and the event reports it — asserted as one concrete value, not merely present.
