# The agent lifecycle — design

Two changes, in order. The first corrects what the supervisor does with an attempt it does not
own. The second states the lifecycle those rules describe, once, and enforces it at the write.

The second cannot come first: there is no point carving current behaviour into a table when
that behaviour is wrong.

## Why

**Four spellings of "is this agent done".** `bus.py` answers that question four ways —
`live()` reads the latest row against `TERMINAL`; `outstanding()` reads the whole history and
treats `idling` as re-opening it; `_reaped()` looks for a supervisor-written terminal; and
`AgentStatus.IDLING` sits *inside* `TERMINAL` while meaning "not finished". A reader at a call
site cannot tell which is meant. Every bug this area has produced was that confusion:

- `live_children` asked one `parent_agent` a question about a task.
- `outstanding` read a latest row that the supervisor's appended `exited` had already masked.
- `COLLECTED` was excluded from `TERMINAL` on the strength of one reading, which made a
  collected agent read as live to the other, breaking `answer_task` on a collected child.
- `in_flight` matched `claimed`/`running` on the latest row, so an agent whose worker had
  spoken was invisible to the orphan sweep.

Four instances, one cause: an agent's lifecycle is a state machine, and it is currently implied
by predicates rather than stated anywhere.

**And two supervisor rules that were never justified.** Both were introduced in the first
supervisor commit and never questioned since:

- On finding rows a previous supervisor left `claimed` or `running`, the loop marks them
  `abandoned` and **returns**, aborting the run.
- On exit, `shutdown` kills every live process and marks each `abandoned`.

Both encode an assumption never written down: *a run is one supervisor's session, and anything
unfinished when that session ends is finished.* That contradicts the rest of the system, where
state deliberately survives a process — `spec.json` and `transcript.jsonl` on disk,
`answer_task` resuming an agent in a later invocation, an idling parent resuming across ticks.
These are the only two places that look at surviving state and declare it dead.

## Part one: the supervisor stops guessing

**Stale rows are not corruption.** They are the ordinary state of a run directory whose previous
supervisor was interrupted, which is a workflow this project supports everywhere else. The
current code treats them as a fatal inconsistency and aborts.

**`shutdown` records nothing and kills nothing.** It stops watching. A worker that outlives the
supervisor finishes and writes its verdict, and the next startup adopts the result; killing it
throws away completed work for no gain. If the process group dies with the parent, the next
startup finds the processes gone and says so. Either way, resolution happens in one place.

**Startup resolves, by checking rather than assuming.** The `running` event records the worker's
pid, so the supervisor can ask instead of guess:

| stale agent | resolution |
|---|---|
| `Reported(verdict)` | record `exited` — the work was done, only the record was left open |
| `Running`, pid alive | leave it — someone is still working |
| `Running`, pid dead | record `crashed` — verified, not assumed |
| `Claimed`, never ran | record `crashed` — no process was ever spawned |

`os.kill(pid, 0)` is the liveness probe. Its hole is pid reuse: it reports that *a* process holds
that id, not that the process is ours. A false "alive" leaves a row stale and its parent waiting.
Closing that needs a start-time comparison or a lease, and neither is worth it yet. Accepted.

**The loop no longer returns on finding stale rows.** It resolves what it can and continues, so
queued work unrelated to the wreckage proceeds.

**No automatic retry.** The project's stated rule — *it never retries; a crash is reported and
the parent decides* — is unchanged. A child whose worker died is closed honestly; its parent
wakes, collects the outcome the supervisor synthesised, and decides. Nothing is silently dropped
and nothing is silently redone.

**`ABANDONED` loses both producers and is deleted.** Shutdown wrote it and the sweep wrote it;
neither does now.

## Part two: the lifecycle, stated once

```
—                      → queued     (supervisor)  → Queued
Queued                 → claimed    (supervisor)  → Claimed
Claimed                → running    (supervisor)  → Running
Claimed                → crashed    (supervisor)  → Lost(crashed)       spawn failed
Running                → verdict    (worker)      → Reported(verdict)
Running                → crashed | timed_out      → Lost(close)         died before speaking
Reported(verdict)      → exited | crashed | timed_out → Closed(verdict)
Closed | Lost          → collected  (worker)      → Collected
```

`verdict ∈ {completed, exhausted, failed, needs_input, idling}`.

**The axis is whether the attempt got to say anything, not whether it succeeded.** A worker that
caught an exception, wrote `outcome.json` and recorded `failed` **spoke**: it is
`Closed(failed)`, not `Lost`. A worker killed mid-run never spoke: `Lost(crashed)`. The
distinction is what a parent needs — `Closed(failed)` has a real message in its outcome file,
`Lost(crashed)` has only what the supervisor synthesised.

`Closed(idling)` is the member that matters most: the one verdict meaning *not finished*. Naming
it in the state is most of the point. `outstanding` stops being a frozenset intersection with a
special case and becomes a question about which state a task's newest attempt is in.

**`Reported → Collected` is illegal.** Today a parent may collect from `Reported`, because
`collect_task` requires only that the task is not outstanding and a worker verdict alone
satisfies that — so a parent can read a child's answer while that child's process is still
exiting. That is the same window closed for waking, still open for collecting. A parent now
waits for the supervisor's close. `Lost → Collected` stays legal: the supervisor writes an
outcome file for a worker that died, so there is something to read.

**Enforcement is at the write.** `Bus.record` is the single choke point — `enqueue`, `claim`,
the supervisor and the tools all go through it. It derives the current state, rejects an illegal
transition, and writes, inside one transaction. The transition function is pure: state plus
status plus source, in; next state or rejection, out.

**Tests get a helper rather than an exemption.** Sixty-two `record` calls in the suite, most
jumping from `enqueue` straight to a verdict — `completed` appears eleven times against
`running` six. Under enforcement those are illegal. A `settle(bus, agent, verdict)` helper
writes `claimed → running → verdict → exited` in one call, so fixtures become both faithful and
shorter. The alternative — exempting tests — is how a documented-but-unenforced machine drifts
from the code, which is the failure this design exists to end.

## What this does not do

**It does not move states out to call sites.** `Bus` keeps its method names; they are
reimplemented over one derivation. Whether callers should ask *what state is this* rather than
*is it outstanding* is a real question and a separate change.

**It does not fix the N+1 reads.** `_has_news` and `uncollected` walk each child's history per
tick. A fold reads the same rows; this is orthogonal.

**It does not add a lease or heartbeat.** The pid check's reuse hole stands, and with it the
residual that two supervisors sharing one `bus.db` can each see only their own processes.

**It does not change the wake's ordering.** `event id > idled_at` is about the total order of
events, not about states, and is unaffected.
