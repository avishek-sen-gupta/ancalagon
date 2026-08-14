# TLA+ Curriculum for the Bus — Implementation Plan

> **Not for agentic workers.** This plan is executed by a human author with an assistant
> guiding, per the working agreement in the spec. Do NOT dispatch subagents to complete
> these tasks: the author writing each specification by hand *is* the deliverable. An agent
> that writes the `.tla` files has destroyed the thing being built.

**Goal:** Teach the author to specify and check concurrent systems in TLA+, using the
ancalagon bus as the running subject, and in the process settle seven open concurrency
findings and the deferred enqueue-guard decision.

**Architecture:** Eight modules. Each introduces one construct on a throwaway toy where the
construct is the only difficulty, then applies that same construct to a model of the harness
where the domain is. Every module ends with TLC either checking a property or producing a
counterexample trace read together. Modules 0–2 are foundation and produce no findings; the
first lands in Module 3.

**Tech Stack:** Raw TLA+ (not PlusCal), TLC via `tla2tools.jar`, Java 25, VS Code with the
TLA+ extension, specifications versioned in the ancalagon repository.

**Spec:** `docs/superpowers/specs/2026-08-14-modelling-the-bus-in-tla-design.md`

## Global Constraints

- **Raw TLA+, never PlusCal.** PlusCal may be read in Module 7 for comparison; nothing in
  `specs/` is written in it.
- **The author writes every `.tla` and `.cfg` file.** The assistant explains constructs, sets
  exercises, reviews, runs TLC, and explains rejections. It does not supply corrected files.
- **This plan contains no solutions.** Exercises state the goal, the constraints, and the TLC
  output that constitutes success. Where the template would demand finished source, this plan
  gives acceptance criteria instead, deliberately.
- **Detours outrank schedule.** A question about stuttering, inductive invariants, or why an
  action is a predicate takes precedence over finishing a module.
- **One commit per module**, containing the specification, its `.cfg`, and the notes.
- **Specifications live in `specs/`** in this repository: `specs/toy/` for throwaway
  constructs, `specs/bus/` for the harness model, `specs/README.md` for how to run TLC.
- **Modules 5–7 are deliberately coarser than 0–4.** Their shape depends on what the earlier
  models find; planning them in step detail now would be inventing findings. They are
  re-planned when Module 4 completes.

---

### Task 0: Toolchain, and what a specification is

**Files:**
- Create: `specs/README.md`
- Create: `specs/toy/Counter.tla`, `specs/toy/Counter.cfg`
- Create: `.gitignore` entry for `specs/**/states/` and `*.toolbox`

**Interfaces:**
- Produces: a working `java -cp tla2tools.jar tlc2.TLC` invocation used by every later task;
  the `specs/` layout every later task writes into.

- [ ] **Step 1: Install the TLA+ extension**

```bash
code --install-extension alygin.vscode-tlaplus
code --list-extensions | grep -i tla
```

Expected: the extension id echoes back. If the marketplace id has changed, search the
Extensions pane for "TLA+" and take the one by Andrew Alygin; the id is then verified with
the same `--list-extensions` call.

- [ ] **Step 2: Fetch tla2tools.jar**

```bash
mkdir -p ~/.local/lib
curl -L -o ~/.local/lib/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar
java -cp ~/.local/lib/tla2tools.jar tlc2.TLC -help | head -5
```

Expected: TLC prints its usage banner. The extension bundles its own copy; this one exists so
the assistant can run TLC from the terminal and show output directly.

- [ ] **Step 3: Concept — what a specification denotes**

Assistant explains, before any syntax: a *state* is an assignment of values to variables; a
*behaviour* is an infinite sequence of states; a *specification* is the set of behaviours it
permits. TLC does not execute a program — it explores a reachable state graph. This framing
is what makes `Init /\ [][Next]_vars` read as a formula rather than a program, and every
later confusion traces back to losing it.

- [ ] **Step 4: Write `Counter.tla`**

Exercise: a single variable `x`, starting at 0, incremented by 1 while below 3. Use only
`VARIABLES`, `Init`, `Next`, `Spec`, and `TypeOK`. Do not consult a tutorial for the
`Spec ==` line — write what you think it should be and we will discuss what you wrote.

Acceptance: the module parses.

- [ ] **Step 5: Write `Counter.cfg` and run TLC**

```bash
cd specs/toy
java -cp ~/.local/lib/tla2tools.jar tlc2.TLC -config Counter.cfg Counter.tla
```

Expected: TLC reports **"Deadlock reached"** with a 4-state trace ending at `x = 3`. This is
the intended outcome, not a mistake. Reading this trace is the exercise.

- [ ] **Step 6: Concept — stuttering, and why the deadlock happened**

Assistant explains why `[][Next]_vars` has a subscript, what a stuttering step is, why the
deadlock is TLC being helpful rather than the specification being wrong, and the two
legitimate responses (`-deadlock` off, or an explicit `Done` action). Author chooses one and
applies it.

Acceptance: TLC reports no errors and a state count.

- [ ] **Step 7: Write `specs/README.md` and commit**

Contents: the TLC invocation, what `specs/toy/` and `specs/bus/` are for, and one line per
specification. Then:

```bash
git add specs .gitignore
git commit -m "Module 0: a specification is a set of behaviours"
```

---

### Task 1: One agent's lifecycle

**Files:**
- Create: `specs/toy/TrafficLight.tla`, `specs/toy/TrafficLight.cfg`
- Create: `specs/bus/Lifecycle.tla`, `specs/bus/Lifecycle.cfg`
- Read: `ancalagon/bus/agent_status.py`, `ancalagon/supervisor/supervisor.py`,
  `ancalagon/worker.py:139-152`

**Interfaces:**
- Consumes: the `specs/` layout and TLC invocation from Task 0.
- Produces: `Status` as the set of eleven statuses, `TERMINAL` as its subset, and the action
  names `Claim`, `Start`, `WorkerFinish`, `Reap` — reused and extended by every later bus
  specification.

- [ ] **Step 1: Concept — an action is a predicate**

Assistant explains: `x' = 1` is not an assignment. An action is a boolean-valued formula over
two states, unprimed for before and primed for after. The consequence that traps every
beginner is that enabling conditions and state changes are the same kind of thing, written
the same way, distinguished only by whether the variable is primed. `UNCHANGED` exists
because an unconstrained primed variable may take *any* value.

- [ ] **Step 2: Write `TrafficLight.tla`**

Exercise: one variable cycling green → amber → red → green. Every action names every
variable's next value, `UNCHANGED` where nothing moves. Invariant `TypeOK` asserting the
variable is always one of the three colours.

Acceptance: TLC explores 3 distinct states, no invariant violation.

- [ ] **Step 3: Break it deliberately**

Exercise: change one action so amber may go to a colour outside the set, and run TLC.

Expected: an invariant violation with a two-state trace. Assistant explains how to read the
trace — which action fired, what changed, why the reported state is the *first* bad one.

- [ ] **Step 4: Read the real status machine**

Author reads `agent_status.py` and lists, from the source, which statuses the supervisor
writes and which the worker writes. Assistant confirms against `supervisor.py` and
`worker.py`. The pair to notice: the worker records `completed` and the supervisor then
records `exited` for the same agent — two terminal events in sequence, legitimately.

- [ ] **Step 5: Write `Lifecycle.tla`**

Exercise: one agent, variable `status`, eleven statuses, actions `Claim`, `Start`,
`WorkerFinish`, `Reap`, and `SpawnFail`. Write `TypeOK`, and write `StatusMachineValid` as
an invariant capturing the transitions the design permits — including terminal-then-terminal.

Acceptance: TLC finds no violation and reports the state count. If it finds one, the
disagreement is between your model and the code, and resolving which is wrong is the point of
the module.

- [ ] **Step 6: Commit**

```bash
git add specs
git commit -m "Module 1: actions are predicates over two states"
```

---

### Task 2: Many agents, one supervisor

**Files:**
- Create: `specs/toy/Mutex.tla`, `specs/toy/Mutex.cfg`
- Modify: `specs/bus/Lifecycle.tla` → generalise to `specs/bus/Queue.tla`, `Queue.cfg`
- Read: `ancalagon/bus/bus.py` (`enqueue`, `claim`), `ancalagon/supervisor/supervisor.py`
  (`_start_queued`)

**Interfaces:**
- Consumes: `Status`, `TERMINAL`, and the action names from Task 1.
- Produces: `Agents` as a `CONSTANT`, `status` as a function `[Agents -> Status]`, and the
  invariants `ClaimedAtMostOnce` and `CapRespected`.

- [ ] **Step 1: Concept — functions as state, and quantified nondeterminism**

Assistant explains `CONSTANTS` and model values; that `status \in [Agents -> Status]` makes
`status` one variable holding a function rather than many variables; `EXCEPT` syntax and why
it exists; and that `\E a \in Agents: Claim(a)` is not a loop — it is nondeterministic choice
that TLC explores exhaustively, which is the entire source of its power and of its state-space
cost.

- [ ] **Step 2: Write `Mutex.tla`**

Exercise: two processes, a shared lock, actions to acquire and release. Invariant: never both
in the critical section.

Acceptance: TLC finds no violation. Then remove the guard from one acquire action and confirm
TLC produces a trace showing both processes inside.

- [ ] **Step 3: Concept — state-space growth**

Assistant explains why the state count grew, what symmetry sets do, and how to read TLC's
"distinct states" versus "states generated" figures. Author sets a symmetry set over `Agents`
and observes the reduction.

- [ ] **Step 4: Write `Queue.tla`**

Exercise: generalise Module 1 to `N` agents. Add a `live` set for spawned processes, honour
`MaxConcurrent`, and model `claim(limit=1)` as claiming exactly one agent per step. Write
`ClaimedAtMostOnce` and `CapRespected`.

Acceptance: TLC checks both invariants across the full state space for `N = 3`,
`MaxConcurrent = 2`, with no violation.

- [ ] **Step 5: Commit**

```bash
git add specs
git commit -m "Module 2: quantified actions are nondeterministic choice"
```

---

### Task 3: The log is the state

**Files:**
- Create: `specs/toy/AppendOnly.tla`, `specs/toy/AppendOnly.cfg`
- Create: `specs/bus/Log.tla`, `specs/bus/Log.cfg`
- Read: `ancalagon/bus/bus.py` (`LATEST`, `_states`, `record`, `active_for`)

**Interfaces:**
- Consumes: `Agents`, `Status`, `TERMINAL`, `CapRespected` from Task 2.
- Produces: `log` as a sequence variable, `Status(a)` as a derived *operator* rather than a
  variable, and `StaleRead` — the modelling of a read taken outside a transaction.

- [ ] **Step 1: Concept — variables versus functions of variables**

Assistant explains sequences (`Seq`, `Append`, `Len`, indexing), and the judgement this module
turns on: `status` was a variable because it was convenient, but in the real system it is
*derived* by `MAX(id)` per agent over an append-only table. Modelling it as a variable
asserts something false — that reading it is atomic with writing it.

- [ ] **Step 2: Write `AppendOnly.tla`**

Exercise: one variable `log`, a sequence. Actions append records, each tagged with an
identifier drawn from a small set. Define `Current(id)` as an operator returning the last
record carrying that identifier, or a default when the sequence holds none.

Acceptance: TLC checks an invariant relating `Current` to the sequence contents for a bounded
log length.

- [ ] **Step 3: Rewrite the bus model over the log**

Exercise: `Log.tla` replaces the `status` variable with a `log` sequence and defines
`Status(a)` as an operator. Every invariant from Task 2 must still hold, unchanged in meaning.

Acceptance: `ClaimedAtMostOnce` and `CapRespected` still check clean. Assistant explains that
what was just done is refinement, informally, and names it.

- [ ] **Step 4: Model the stale read, and state findings 1 and 2**

Exercise: split a decision that reads `Status(a)` and then acts into two steps, so other
actions may interleave between them. Add the `active_for` query as an operator and write
`AtMostOneLiveProcessPerTask` over the `live` set — not over status.

Expected: TLC produces a counterexample. Two are anticipated: the TOCTOU between reading and
enqueuing (finding 2), and the window where `Status(a)` is terminal while the process is still
in `live` (finding 1). Confirming *which* it finds first, and whether it finds both, is the
deliverable.

- [ ] **Step 5: Record the findings and commit**

Author writes the traces and their interpretation into `specs/README.md` against findings 1
and 2. Then:

```bash
git add specs
git commit -m "Module 3: derived state, and the first two findings"
```

---

### Task 4: Atomicity and the two-store problem

**Files:**
- Create: `specs/toy/Transfer.tla`, `specs/toy/Transfer.cfg`
- Create: `specs/bus/TwoStore.tla`, `specs/bus/TwoStore.cfg`
- Read: `ancalagon/worker.py:139-152`, `ancalagon/supervisor/supervisor.py`
  (`_write_timeout_outcome`), `ancalagon/cli.py` (outcome deletion),
  `ancalagon/tools/delegate/collect_task.py`

**Interfaces:**
- Consumes: `log`, `Status(a)`, `live` from Task 3.
- Produces: `outcome` as a second store variable, `Crash(p)` as an action enabled in every
  state, and `OutcomeAgreesWithLog`.

- [ ] **Step 1: Concept — one step is a decision, not a fact**

Assistant explains that atomicity in a specification is chosen by where actions are drawn, and
that this is the single most consequential modelling judgement. Two writes in one action
assert a transaction exists. The code has no transaction spanning `bus.db` and the filesystem,
so the model must not draw them as one action.

- [ ] **Step 2: Write `Transfer.tla`**

Exercise: two accounts, a transfer that debits and credits in *separate* actions, and a
`Crash` action enabled in every state that halts the process. Invariant: total is conserved.

Expected: TLC produces a trace where the crash lands between debit and credit and money
vanishes. Assistant explains why crash-as-an-action-everywhere is the standard idiom.

- [ ] **Step 3: Model the worker's record-then-write**

Exercise: add `outcome` to the bus model. Split the worker's completion into
`RecordTerminal` then `WriteOutcome`, with `Crash` available between. Write
`OutcomeAgreesWithLog` — and state precisely what agreement means before writing it, since
the code's intent is not obvious and deciding it is half the exercise.

Expected: a counterexample for finding 4 — log terminal, no outcome file, `collect_task`
permanently reporting "no outcome yet".

- [ ] **Step 4: Model findings 5, 6, and 7**

Exercise: add the worker's exception path (outcome written, no event recorded), the CLI's
delete-before-enqueue against a surviving worker, and `_write_timeout_outcome`'s
exists-then-write against the worker it killed.

Expected: each is confirmed with a trace or refuted with a clean check. A refutation is a
result and gets recorded as one.

- [ ] **Step 5: Record findings and commit**

```bash
git add specs
git commit -m "Module 4: atomicity is a modelling decision"
```

---

### Task 5: Liveness and fairness

**Files:**
- Create: `specs/toy/Server.tla`, `specs/bus/Liveness.tla`, and their `.cfg` files

Coarser by design; re-planned in step detail when Task 4 completes, because which liveness
properties are worth checking depends on what Modules 3 and 4 found.

- [ ] Concept: `[]`, `<>`, `~>`; why an invariant cannot express "eventually"; weak versus
      strong fairness; why the default specification has neither; why TLC checks temporal
      properties by a different and far slower algorithm.
- [ ] Toy: a server where "every request eventually served" fails without `WF` and passes
      with it. The author must predict which fairness is needed before running TLC.
- [ ] Real: `EveryAgentEventuallyTerminal`, `SupervisorEventuallyIdle`, `NoLostQueuedWork`.
- [ ] Expected finding: `run_until_idle`'s orphan branch returning while agents are still
      queued (finding 3), and delegation starvation under `MaxConcurrent`.
- [ ] Commit: `"Module 5: liveness needs fairness, and fairness must be stated"`

---

### Task 6: The failure detector

**Files:**
- Create: `specs/bus/Detector.tla`, `specs/bus/Detector.cfg`

Coarser by design; re-planned when Task 5 completes.

- [ ] Concept: parameterising a specification over a design choice; modelling an oracle that
      may be wrong in a bounded way; comparing designs by which properties survive rather than
      by argument.
- [ ] Exercise: three detectors as `CONSTANT` instantiations — trust-the-log, pid-liveness,
      lease-with-heartbeat — each checked against `AtMostOneLiveProcessPerTask` and against
      the Module 5 liveness properties.
- [ ] Deliverable: a table of which properties hold under which detector, and the false-positive
      window each admits. **This is the input the deferred enqueue-guard work package needs.**
- [ ] Commit: `"Module 6: choosing a failure detector, with evidence"`

---

### Task 7: Specification to code

**Files:**
- Create: `tests/unit/test_bus_model.py`
- Modify: `specs/README.md`

Coarser by design; re-planned when Task 6 completes.

- [ ] Concept: refinement and simulation stated informally; why the gap between specification
      and implementation cannot be closed automatically here; what a `RuleBasedStateMachine`
      can and cannot show.
- [ ] Exercise: derive a Hypothesis state machine from the specification's actions — one rule
      per action, the specification's invariants as `@invariant` methods — running against the
      real `Bus` and a real temporary database.
- [ ] Acceptance: the property test finds the confirmed findings from Modules 3 and 4 against
      the real code, or explains why it cannot reach them.
- [ ] Commit: `"Module 7: the same invariants, against the real bus"`

---

## Self-review against the spec

**Coverage.** All eight modules present, in the spec's order. All seven findings assigned:
1 and 2 to Task 3, 4 through 7 to Task 4, 3 to Task 5. All named properties assigned:
`ClaimedAtMostOnce` and `CapRespected` to Task 2, `AtMostOneLiveProcessPerTask` to Tasks 3 and
6, `StatusMachineValid` to Task 1, `OutcomeAgreesWithLog` to Task 4, the three liveness
properties to Task 5. `DepthBounded` is **not** assigned a task — delegation depth only becomes
interesting alongside the starvation case, so it is folded into Task 5 and named there when
that task is re-planned.

**Placeholders.** None. Where the template requires implementation code, this plan gives the
exercise and its acceptance criterion instead, deliberately and for the reason stated in the
Global Constraints.

**Consistency.** `Status`, `TERMINAL`, `Agents`, `log`, `live`, `outcome`, and the action
names `Claim`, `Start`, `WorkerFinish`, `Reap`, `Crash` are used identically across tasks.
`AtMostOneLiveProcessPerTask` is phrased over `live` in both places it appears, never over
status — which is finding 1 and the reason for the name.
