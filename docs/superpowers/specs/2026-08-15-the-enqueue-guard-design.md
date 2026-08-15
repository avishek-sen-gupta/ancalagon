# The enqueue guard — design

Resolves the question deferred in
`2026-08-14-modelling-the-bus-in-tla-design.md`: whether `Bus.enqueue` should refuse a task
that already has a live agent, and what it should believe about liveness.

## What goes wrong without it

One failure, four faces: two worker processes alive in the same task directory.

**Interleaved transcripts.** `Transcript` appends and flushes per message. Two workers make
one file holding two conversations shuffled together. That file *is* the conversation
replayed to the provider on resume, and `history.load` reads it as a single sequence, so the
result is a corrupt history with conflicting turns and no way to separate them afterwards.

**Tool outputs overwriting each other.** `ToolContext` numbers its files `0000-…`, `0001-…`
from an `itertools.count()` held **per instance**. Two workers both start at zero in the same
`tools/` directory, so a tool result recorded in one transcript can point at a path now
holding another agent's output. Wrong rather than broken, which is worse.

**The wrong attempt's answer collected.** `worker.main` records its terminal status and
*then* writes `outcome.json`. Between those two statements the task looks finished to the
bus and has no answer on disk. A parent polling in that window sees neither a live agent nor
a result, re-delegates, and the original worker's `outcome.json` lands afterwards —
so `collect_task` hands the parent the previous attempt's answer while a new agent runs.

**Double spend.** Two workers on one task is twice the model calls, and the loser's are waste.

## Why the obvious guards do not work

**Latest status is not liveness.** `active_for` treats any terminal status as inactive, and a
worker records its terminal status before writing its outcome and exiting. The task therefore
looks free while a process is still writing to it.

This is not theoretical. `answer_task` shipped with a guard requiring the agent's *latest*
status to be `needs_input`, and the first end-to-end test against real worker processes showed
every real agent ends `exited` — because the worker records `needs_input` and the supervisor
then records `exited`. The guard would have refused every answer in production. The
terminal-then-terminal pair was written down in the TLA+ design hours earlier as a property
that looks true and is not, and the guard was written against it anyway.

**Reading and enqueuing separately is a race.** `Delegate` consults `active_for` in one
statement and enqueues in another. Two parents delegating the same `task_id` can both observe
nothing active before either enqueues.

## Choosing a failure detector

The system cannot distinguish a crashed worker from a slow one without deciding how it
detects death. Three candidates, and the choice is a design commitment with a stated failure
mode rather than a correct answer.

**Lease with heartbeat.** The job-queue answer, and what multi-worker harnesses generally
adopt, because it works across machines where no shared kernel exists. Its failure mode is
exactly the one being prevented: a live-but-slow worker misses a renewal, the lease expires,
another worker claims the task, and two processes share a directory. Ancalagon runs on one
machine, so this buys distribution it does not need and pays for it in false positives.

**An advisory file lock (`flock`).** The kernel releases it when the holder dies, however it
dies, which makes it a *reliable* detector rather than an inference. It costs a lock file per
task, is Unix-only, and is unreliable over NFS. The platform limit is not a new constraint —
the tools already shell out to `file`, `strings`, `sed` and `ctags` — but the file is new
state, and the mechanism is separate from everything else the bus knows.

**Process liveness, which is the choice.** The supervisor already records each worker's pid on
its `running` event, so the bus holds the answer already. `os.kill(pid, 0)` reports whether
that process exists. Pid reuse makes this an inference rather than a fact, and the inference
is hardened by checking the process's command line names this task directory: a false positive
then requires a recycled pid *and* the new process being an ancalagon worker on the same
directory.

It wins on fit rather than on purity. It needs no new file, no dependency, and no platform
primitive, and — decisively — it composes with the transaction that already exists.

## The design

**The check belongs inside `Bus.enqueue`, in the `BEGIN IMMEDIATE` it already opens.** That is
what closes the race: two enqueues serialise, the first reclaims or refuses, and the second
sees the outcome of the first. A check anywhere else reintroduces the gap between deciding and
acting.

Within that transaction, for the task at `dir`:

1. Find agents whose latest status is `claimed` or `running` — the ones the bus believes are
   working.
2. Ask a `Liveness` protocol about each. A `pid` of 0 means the supervisor never recorded a
   start, so the agent never ran and is dead. Otherwise the process must exist *and* its
   command line must name this task directory.
3. Any agent found dead gets an `abandoned` event, with the reclamation recorded rather than
   silent.
4. If any agent is alive, raise, naming it and its status.
5. Otherwise insert the new agent as now.

`Liveness` is a Protocol with one method, alongside `Clock`, `Spawner` and `Process`, so the
supervisor's existing testing pattern extends to it: the real implementation calls `os.kill`
and reads the command line; tests inject a fake and choose who is alive.

**Three call sites collapse into one.** `Delegate` currently guards with `active_for` and
`answer_task` does the same; both become unnecessary and are removed, since `enqueue` refuses
and they report what it raises. The CLI, which has no guard at all today, gets one for free —
which is the path where two `ancalagon run` invocations against one `run_dir` currently
collide unimpeded.

## What it does not cover

**A wedged but living worker.** No detector helps: the process exists, so the task stays
locked until `agent_timeout_s` kills it. That is the supervisor's job and stays there.

**More than one machine.** The check is meaningless for a pid on another host. The lease is the
migration path if that ever arrives, and the guard's shape would not change — only what backs
it.

**Anything outside the bus.** A process started by hand, not through the supervisor, records no
pid and is invisible.

## Testing

One behaviour test with an injected `Liveness`: enqueuing against a task whose agent is alive
is refused; against one whose agent is dead it succeeds and leaves an `abandoned` event for
the reclaimed agent; a `claimed` agent with `pid = 0` counts as dead; and a recycled pid whose
command line names a different directory counts as dead.

Then the existing suites, which should need no changes beyond removing the two now-redundant
guards — and the scripted-model integration test already runs two workers concurrently, so it
exercises the real path.
