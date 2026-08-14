# Modelling the bus in TLA+ — design

## Why this exists

Two goals, deliberately unequal in weight.

**Primary: learn to model systems in TLA+.** The author has read about TLA+ and never
written a specification. This work is the vehicle for learning it properly — raw TLA+
rather than PlusCal, written by hand rather than read, with each construct met first on a
toy where it is the only difficulty and then on the real system where it is not.

**Secondary: settle the concurrency questions in `ancalagon/bus/`.** The harness runs a
supervisor and several worker processes against one SQLite database and a shared
filesystem. Several safety and liveness questions about that arrangement are open, and one
of them — whether `Bus.enqueue` should refuse a task that already has a live agent — was
deferred precisely because it has no answer that does not first require deciding how the
system detects that a process has died.

The ordering matters when the two goals conflict. A detour that teaches a construct
properly is worth taking even when it does not advance the proof. A shortcut that reaches a
verdict faster while leaving the reader unable to reproduce the reasoning is not.

## What kind of system this is

Not distributed in the consensus sense: one machine, one SQLite file, a fixed set of
processes, no replication and no partitions. SQLite's locking already gives linearizable
writes. There is nothing here to model about agreement.

Three hazards remain, and every known bug in this area is an instance of one of them.

**Two stores with no joint transaction.** `bus.db` and the filesystem are written
separately. The worker records its terminal status and *then* writes `outcome.json`; the
supervisor writes a timeout outcome for a process it has just killed. No transaction spans
the pair.

**Process liveness is unobservable.** Nothing heartbeats. `in_flight()` is a claim about the
world that the database cannot verify, so crashed and slow are indistinguishable. This is
why the enqueue guard has no purely mechanical answer: the system must *choose* a failure
detector, and the choice has a stated failure mode rather than a correct value.

**State is derived, not stored.** Current status is the latest event per agent, computed by
the `LATEST` query. Those reads happen outside the `BEGIN IMMEDIATE` transactions, so every
decision is taken on a snapshot that may already be stale.

## What is modelled, and what is not

In scope: agent lifecycle and its two writers, the task queue, claiming, the concurrency
cap, the append-only event log and the derived-state query, `outcome.json` as a second
store, process crash and kill, delegation to the depth the cap makes interesting, and the
failure detector as a parameter.

Out of scope, permanently: the session loop, tool dispatch, the LLM and its retries, the
workspace path checks, budgets and metering, transcript repair, and SQLite's internals. The
model assumes SQLite transactions are atomic and serialisable rather than proving it.

The model is a description of the design, not of the code. It cannot catch an
implementation that fails to match it. Module 7 addresses that gap directly and partially;
nothing closes it entirely.

## Findings that motivated this, and their status

Read from the source, not reproduced. Each is a hypothesis the model should confirm or
refute, and confirming a *refutation* is as valuable as confirming a bug.

1. **`active_for` goes empty while the process is alive.** The worker records `completed` —
   a terminal status — before writing `outcome.json` and well before its process exits. From
   that record until the supervisor reaps, `active_for` reports no active agent for a task
   whose worker is still running and still writing. `Delegate`'s guard consults exactly this
   query, so a re-delegation can be admitted into a directory that already has a live
   writer, putting two processes on one `transcript.jsonl`.

2. **TOCTOU between `active_for` and `enqueue`.** The guard reads in one statement and
   enqueues in another. Two workers delegating the same `task_id` can both observe no active
   agent before either enqueues.

3. **`run_until_idle` returns with work still queued.** The orphan branch records
   `abandoned` for in-flight agents it does not own and returns without re-checking
   `queued_count()`.

4. **Record-then-write is not atomic.** A worker that dies between `bus.record(terminal)`
   and `outcome_path.write_text` leaves a database saying `completed` and no outcome file.
   `collect_task` reads status from the bus and the answer from the file, so it reports "no
   outcome yet" for such an agent permanently.

5. **The worker's exception path is the mirror image.** It writes `outcome.json` and records
   no event, relying on the supervisor to infer `crashed` from exit code 1. If the supervisor
   is gone, the agent stays `running` forever.

6. **The CLI deletes the previous `outcome.json` before enqueuing.** A still-live worker
   from a killed run can write its outcome after that delete, and it will be read as the new
   agent's answer.

7. **`_write_timeout_outcome` checks `exists()` then writes**, racing the worker it has just
   killed, since `kill` is asynchronous.

A property proposed during review and **withdrawn before writing this**:
`NoEventAfterTerminal` is false of the real system by design, because the worker's
`completed` is followed by the supervisor's `exited`. It is recorded here because the
retraction is instructive: the first value of writing a specification is that it forces the
status machine to be stated, and a wrong belief about it does not survive that.

## Properties

Safety, to be stated precisely in the modules that can express them:

- `AtMostOneLiveProcessPerTask` — at most one *process* writing a task directory. Note this
  is deliberately not phrased over agent status, because finding 1 shows status is the wrong
  observable.
- `ClaimedAtMostOnce` — no agent is spawned twice.
- `CapRespected` — live processes never exceed `max_concurrent`.
- `StatusMachineValid` — the event sequence for an agent is a path the design permits,
  including the legitimate terminal-then-terminal pairs.
- `OutcomeAgreesWithLog` — whatever relationship between `outcome.json` and the event log
  the design intends, stated explicitly once Module 4 forces the question.
- `DepthBounded` — delegation never exceeds `max_depth`.

Liveness:

- `EveryAgentEventuallyTerminal`, under fairness assumptions the model states rather than
  assumes.
- `SupervisorEventuallyIdle`.
- `NoLostQueuedWork` — nothing remains queued when the supervisor returns.

## The curriculum

Eight modules. Each introduces its construct on a throwaway toy where the construct is the
only difficulty, then applies the same construct to the harness where the domain is. Every
module ends with TLC either checking a property or producing a trace to read together.

**Module 0 — What a specification is.** Behaviours as infinite sequences of states, states
as assignments to variables, a specification as a set of behaviours. Module header,
`EXTENDS`, `VARIABLES`, `Init`, `Next`, `Spec == Init /\ [][Next]_vars`, and why the
subscript exists. Toy: a counter that deadlocks, so the first TLC output is an error worth
reading. Setup: `tla2tools.jar`, the VS Code extension, the `specs/` tree, a `.cfg` file.

**Module 1 — One agent's lifecycle.** Actions as before/after predicates; that `x' = 1` is a
constraint rather than an assignment, and that enabling conditions and state changes are the
same kind of thing; `UNCHANGED`; `TypeOK`; reading a violation trace. Toy: a traffic light.
Real: one agent across the eleven statuses with both writers explicit.

**Module 2 — Many agents.** `CONSTANTS` and model values; functions as state; `EXCEPT`;
`\E a \in Agents` as nondeterminism TLC explores; state-space growth and symmetry sets. Toy:
a two-process mutex. Real: the queue, `claim(limit=1)`, the concurrency cap. Properties:
`ClaimedAtMostOnce`, `CapRespected`.

**Module 3 — The log is the state.** Sequences; the judgement of what is a variable versus
what is a function of variables. The `status` variable is replaced by a `log` sequence with
`Status(a)` as an operator, mirroring `LATEST`. Then the choice that the third hazard —
derived state read outside a transaction — lives in: representing a read that returns a
stale snapshot. Findings 1 and 2 are stated here and decided in Module 6.

**Module 4 — Atomicity and the two-store problem.** That "one step" is a modelling decision;
splitting an action to model a non-atomic pair; crash as an action enabled everywhere. Toy: a
non-atomic transfer. Real: `outcome.json` as a second variable and the worker's
record-then-write as two steps. Findings 4 through 7 are decided here.

**Module 5 — Liveness and fairness.** `[]`, `<>`, `~>`; why an invariant cannot express
"eventually"; weak versus strong fairness and why the default specification has neither. Toy:
a server where "eventually served" fails without `WF` and passes with it. Real:
`EveryAgentEventuallyTerminal`, `NoLostQueuedWork`, and delegation starvation under the cap.

**Module 6 — The failure detector.** Parameterising a specification over a design choice;
modelling an unreliable oracle. Three detectors — trust-the-log, pid-liveness, and
lease-with-heartbeat — each checked against `AtMostOneLiveProcessPerTask`. This module
produces the enqueue-guard decision.

**Module 7 — Specification to code.** Refinement stated informally, why it cannot be checked
automatically here, and the mechanical derivation of a Hypothesis `RuleBasedStateMachine`
from the specification's actions — so the same invariants run against the real `Bus`.

Modules 0 through 2 are foundation and produce no findings. The first lands in Module 3.

## Working agreement

The author writes the `.tla` files. The assistant explains each construct, sets the
exercise, reviews what was written, runs TLC, and explains why TLA+ rejects what it rejects
rather than supplying a corrected file. Errors are the curriculum, not an interruption to it.

Detours are expected and welcome; a question about why stuttering is needed, or what makes
an invariant inductive, takes precedence over finishing a module on schedule. Either party
may propose switching to write-with-annotation for a stretch when a construct is more
efficiently shown than discovered.

## Toolchain and layout

Java 25 is present. `tla2tools.jar` is not, and the VS Code TLA+ extension is not installed;
both are Module 0 tasks. Specifications live in the ancalagon repository so they are
versioned beside the code they describe.

```
specs/
    toy/          one throwaway specification per construct
    bus/          the harness model, grown module by module
    README.md     how to run TLC, and what each specification covers
```

Each module's work is committed separately, with the specification and its `.cfg` in the
same commit as the notes explaining it.

## Success criteria

The primary goal is met when the author can write an unfamiliar specification without
assistance: choose the variables, state the actions, express both a safety and a liveness
property, run TLC, and read a counterexample trace.

The secondary goal is met when each of the seven findings above is confirmed or refuted with
a trace or a checked invariant, and when the enqueue-guard work package can be specified
with its failure detector named and its failure mode stated.

The two goals are compatible for most of the work. Where they conflict, the primary wins.
