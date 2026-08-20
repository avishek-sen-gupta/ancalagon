# One terminal row, written by the supervisor

## The problem

An agent's ending is recorded twice, by two processes, in two stores.

The worker records its verdict to `agent_events` and writes `outcome.json`. The supervisor
later observes the process is gone and records a close — and, when the worker left no outcome,
fabricates one so the parent has something to read. Three writers, two stores, nothing atomic
between them.

Every defect in this area comes from the gaps.

- A worker killed between its two writes leaves a verdict with no answer on disk. Its parent
  sees a settled child, collects, and finds nothing. The supervisor's fabricated `Failed` then
  contradicts the `completed` already in the log.
- A worker that raises outside the session writes a `Failed` outcome and records nothing, so
  it can only ever be `Lost` — making `Closed(failed)`, the example the whole spoke/silent
  axis was designed around, unreachable in production.
- A worker that exits 0 without writing anything is recorded `exited` and gets no fabricated
  outcome, because fabrication is triggered by the *status* rather than by the file's absence.
  Its parent polls forever.
- `collect_task` decides whether a child has finished by whether a file exists. That defect
  has been fixed twice — once for crashed workers, once for agents killed at startup — each
  time by teaching another death path to fabricate a file. A third death path reopens it.
- An agent adopted at startup cannot be reaped like a spawned one, because the exit code of a
  process we did not fork is unavailable. Watching it means a second mechanism.

These have been patched individually. They are one defect: **more than one writer describes
one event.**

## What changes

Two rules, and everything else follows.

1. **The worker never records to the bus about itself.** It writes `outcome.json` and exits.
2. **The supervisor never writes `outcome.json`.** It writes one terminal row per agent.

So each store has exactly one writer for an agent's ending. `outcome.json` is the worker's
account and nothing else ever creates it. The terminal row is the supervisor's, and it carries
both facts — that the process ended, and what the worker said before it did.

```
agent_events for one agent:
    queued  claimed  running  <one terminal row>  [collected]
```

`source` becomes honest: every row about an agent's own lifecycle is written by the
supervisor. The worker's remaining bus writes concern *other* agents — `collected` on a child,
`queued` on a new one — which is a different claim and keeps `source = worker`.

## The terminal row

The supervisor reads `outcome.json` when it closes an agent.

| what it finds | status recorded | state |
|---|---|---|
| an outcome | that outcome's `kind` | `Closed(verdict)` |
| nothing | `crashed`, or `timed_out` if we killed it | `Lost(close)` |

Because the supervisor no longer writes outcome files, "an outcome exists" and "the worker
spoke" are the same statement. There is no marker to check, no ordering rule to obey, and no
way for the supervisor to mistake its own writing for a worker's. The invariant is structural:

> **`Closed` means there is an answer on disk. `Lost` means there is not.**

The spoke-or-silent axis is unchanged, and is now carried by the status alone, because
`source` no longer varies: a verdict status means the worker spoke, a close status means it
did not. Verdicts and closes remain disjoint sets.

`exited` stops being a status any agent receives. A worker that finished cleanly is recorded
as whatever it said — `completed`, `idling`, `needs_input`. "The process exited" was never
information about the *attempt*; it is information about a process, and the exit code
continues to be recorded in `exit_code` where we have it.

## Collecting from a child that never spoke

`collect_task` stops asking the filesystem whether a child has finished, and asks the bus.

- newest attempt is `Closed` → read `outcome.json`, which the invariant guarantees is there,
  and return the typed answer
- newest attempt is `Lost` → report how it ended from the row, without touching the disk
- anything else → not finished yet

This is what the fabricated outcomes existed to paper over. A killed child has no answer, and
"no answer, killed after 600s" is a complete report — better than a `Failed` carrying an
invented `Budget(0, 0)` and a summary assembled from an exit code.

`TimedOut` and `OutcomeKind.TIMED_OUT` are deleted with them. The session never produces a
`TimedOut`; only the supervisor did, and only to fabricate a file. `timed_out` survives as
what it always was — a close status, one name doing one job.

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
- A worker that exits 0 having written nothing is `Lost(crashed)`, and its parent collects a
  report of that from the bus rather than polling for a file that will never appear.
- `collect_task` reads the bus, so no future death path can reopen the defect it has been
  fixed for twice.
- An adopted agent is reaped like any other, on any OS, with no `kqueue` and no `pidfd`.
- **`ancalagon run` exits 1 again when the root produced no answer.** It currently exits 0 and
  prints a fabricated outcome, because the supervisor manufactured one on the root's behalf.

## Costs, accepted

**A parent sees a child's verdict one tick later**, because the verdict reaches the bus when
the supervisor reaps rather than when the worker records. `check_task` lags by a poll
interval. Nothing waits on that edge.

**The bus stops being a live record of worker progress.** Reading `agent_events` mid-run shows
`running` until the reap, where it used to show the worker's own report. `transcript.jsonl`
and `outcome.json` remain, and `model_calls` is still written by the worker as it goes, so
token spend is still observable in real time.

**The supervisor parses `outcome.json`.** It needs `kind` and nothing else, so it reads the
file into a one-field frozen model rather than resolving the role's answer class the way
`collect_task` does. This is a typed read at a boundary, not a JSON blob.

**A parent loses the structured shape of a killed child's ending.** It gets a status and a
summary from the row instead of an `Outcome` model. The model it used to get was fabricated —
a zeroed budget and a summary built from an exit code — so what is lost is the appearance of
structure, not structure.

**A worker whose supervisor dies has no verdict in the bus until a supervisor returns.** The
answer is safe on disk throughout; only the log lags. Startup resolution reads the file and
records the row, so the lag ends when the run resumes.

## Migration

`exited` leaves `AgentStatus` and the schema's `CHECK`. `001_init` is edited in place, as it
is the only migration and run directories are disposable.

Existing run databases carry `exited` rows and worker-written verdict rows. They are not
migrated and will not fold: an agent with both a worker verdict and a supervisor `exited` is a
sequence the new table rejects. This is accepted — a run directory is disposable, and the
alternative is carrying a compatibility branch through the transition table, which is the
thing this design exists to keep single.

## Residuals

- **Two supervisors sharing one `bus.db`** remain out of scope, as in the previous design.
  Adoption assumes one supervisor at a time; two would each adopt the other's workers.
- **`wakeable`/`_has_news` is still an N+1 per tick.** Unchanged by this work, and still the
  polling cost worth addressing separately.
- **A worker that writes a partial `outcome.json` and is killed mid-write** leaves a file that
  will not parse. The supervisor records `Closed` from a `kind` it cannot read, or the parent
  fails to validate. Not introduced here — the same risk exists today — but the invariant
  makes it easier to state: file presence is trusted, file integrity is not.
