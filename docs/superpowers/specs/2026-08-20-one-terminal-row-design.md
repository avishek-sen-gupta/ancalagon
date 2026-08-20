# One terminal row, written by the supervisor

## The problem

An agent's ending is recorded twice, by two processes, in two stores.

The worker records its verdict to `agent_events` and writes `outcome.json`. The supervisor
later observes the process is gone and records a close. Two writes by the worker, one by the
supervisor, none of them atomic with each other.

Every defect in this area comes from the gaps between them.

- A worker killed between its two writes leaves a verdict with no answer on disk. Its parent
  sees a settled child, collects, and finds nothing. The supervisor's synthesised `Failed`
  then contradicts the `completed` already in the log.
- A worker that raises outside the session writes a `Failed` outcome and records nothing, so
  it can only ever be `Lost` — making `Closed(failed)`, the example the whole spoke/silent
  axis was designed around, unreachable in production.
- A worker that exits 0 without writing anything is recorded `exited` and gets no synthesised
  outcome, because synthesis is triggered by the *status* rather than by the file's absence.
  Its parent polls forever.
- An agent adopted at startup cannot be reaped like a spawned one, because the exit code of a
  process we did not fork is unavailable. Watching it means a second mechanism.

These have been patched individually. They are one defect: **two writers describe one event.**

## What changes

The worker stops recording its own verdict. It writes `outcome.json` and exits.

The supervisor writes exactly one terminal row per agent, and that row carries both facts —
that the process ended, and what the worker said before it did.

```
agent_events for one agent:
    queued  claimed  running  <one terminal row>  [collected]
```

`source` becomes honest: every row about an agent's own lifecycle is written by the
supervisor. The worker's remaining bus writes concern *other* agents — `collected` on a
child, `queued` on a new one — which is a different claim and keeps `source = worker`.

## The terminal row

The supervisor reads `outcome.json` when it closes an agent.

| what it finds | status recorded | state |
|---|---|---|
| an outcome the worker wrote | that outcome's `kind` | `Closed(verdict)` |
| no outcome | `crashed`, or `timed_out` if we killed it | `Lost(close)` |

The spoke-or-silent axis is unchanged. It is now carried by the status alone, because
`source` no longer varies: a verdict status means the worker spoke, a close status means it
did not. Verdicts and closes remain disjoint sets.

`exited` stops being a status any agent receives. A worker that finished cleanly is recorded
as whatever it said — `completed`, `idling`, `needs_input`. "The process exited" was never
information about the *attempt*; it is information about a process, and the exit code
continues to be recorded in `exit_code` where we have it.

## Which outcomes count as the worker speaking

The supervisor also *writes* outcome files — a `TimedOut` when it kills a worker, a `Failed`
when one dies silently — so the file's presence alone does not prove the worker wrote it.
`kind` cannot settle it either: `Failed` is written by both, and `TimedOut` is an
`OutcomeKind` as well as a close status.

Two ordering rules make the question unnecessary rather than answering it:

1. **The supervisor records the terminal row before it synthesises an outcome.** So at the
   moment it reads `outcome.json` to decide what to record, any file it finds is the
   worker's. The supervisor has not written one yet and never will for an agent it is about
   to close as `Lost`.
2. **A closed agent with no outcome file is repaired at startup.** If rule 1's second write
   is lost — the supervisor dies between recording and synthesising — the next supervisor
   finds an attempt in `Closed` or `Lost` whose task directory has no `outcome.json`, and
   writes one. This is the only case where the supervisor synthesises an outcome for an agent
   it did not just close.

Together these give a single invariant worth stating plainly: **an `outcome.json` present
when the supervisor closes an agent was written by that agent's worker.** No marker, no
sniffing a summary, no second filename.

Note that rule 1 inverts the worker's own ordering, and deliberately. The worker writes its
file *before* it would have recorded anything, because losing the answer is worse than losing
the label. The supervisor records *before* it writes, because for a `Lost` agent the row is
the fact and the file is a courtesy to the parent. Each writes the thing it cannot reconstruct
first.

## States

`Reported` is deleted. It existed only to name the interval between the worker's record and
the supervisor's close, and that interval no longer exists.

```
Nascent -> Queued -> Claimed -> Running -> Closed(verdict) | Lost(close) -> Collected
```

Seven states. `next_state`'s table narrows accordingly: from `Running`, a supervisor-written
verdict yields `Closed` and a supervisor-written close yields `Lost`. From `Claimed`, only a
close is legal — a spawn that failed never started a worker, so there is no outcome to read
and nothing that could have spoken. The `Reported` case and the `Running -> verdict(worker)`
case both go.

`unreaped()` becomes `Claimed` or `Running`. `Supervisor._resolve_one`'s "did the worker
already report" branch disappears, because a worker can no longer have reported without the
supervisor having closed it.

## Adoption

With the terminal row owned by the supervisor, an adopted agent needs nothing special.

`Liveness.is_running(pid)` answers whether it is still going. When it stops, the supervisor
reads `outcome.json` and records the terminal row by the same rule it uses for a process it
spawned. The exit code is absent for an adopted process and present for a spawned one, and it
was never what decided anything.

So adopted agents enter `self.live` through a `Process` adapter backed by `Liveness` whose
`poll()` reports `None` while the pid is alive. Nothing is fabricated, there is no second
collection to track, and `run_until_idle` cannot return while an adopted worker is running —
which is the bug that started this.

`_resolve_running`'s "leave it alone" branch becomes an adoption instead of a no-op. An
adopted agent counts against `max_concurrent`, because one supervisor runs at a time and an
adopted worker is real load.

## What this fixes

- The kill-in-the-gap window is gone, not mitigated. There is one write where there were two.
- A worker that raises outside the session is `Closed(failed)`, because its `Failed` outcome
  file is what the supervisor records from. The axis's own example becomes reachable.
- A worker that exits 0 having written nothing is `Lost(crashed)` with a synthesised outcome
  its parent can collect. Synthesis is driven by the file's absence, which is the fact, rather
  than by the status, which was a proxy for it.
- An adopted agent is reaped like any other, on any OS, with no `kqueue` and no `pidfd`.

## Costs, accepted

**A parent sees a child's verdict one tick later**, because the verdict now reaches the bus
when the supervisor reaps rather than when the worker records. `check_task` lags by a poll
interval. Nothing waits on that edge.

**The bus stops being a live record of worker progress.** Reading `agent_events` mid-run shows
`running` until the reap, where it used to show the worker's own report. `transcript.jsonl`
and `outcome.json` remain, and `model_calls` is still written by the worker as it goes, so
token spend is still observable in real time.

**The supervisor parses `outcome.json`.** It needs `kind` and nothing else, so it reads the
file into a one-field frozen model rather than resolving the role's answer class the way
`collect_task` does. This is a typed read at a boundary, not a JSON blob.

**A worker whose supervisor dies has no verdict in the bus until a supervisor returns.** The
answer is safe on disk throughout; only the log lags. Startup resolution reads the file and
records the row, so the lag ends when the run resumes.

## Migration

`exited` leaves `AgentStatus` and the schema's `CHECK`. `001_init` is edited in place, as it
is the only migration and run directories are disposable.

Existing run databases carry `exited` rows and worker-written verdict rows. They are not
migrated and will not fold: an agent with both a worker verdict and a supervisor `exited` is
a sequence the new table rejects. This is accepted — a run directory is disposable, and the
alternative is carrying a compatibility branch through the transition table, which is the
thing this design exists to keep single.

## Residuals

- **`timed_out` is both a close status and an `OutcomeKind`.** It stays both. The ordering
  rules mean the supervisor never reads its own `TimedOut` file as a worker verdict, so the
  overlap is harmless, but it is a name doing two jobs.
- **Two supervisors sharing one `bus.db`** remain out of scope, as in the previous design.
  Adoption assumes one supervisor at a time; two would each adopt the other's workers.
- **`wakeable`/`_has_news` is still an N+1 per tick.** Unchanged by this work, and still the
  polling cost worth addressing separately.
