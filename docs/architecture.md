# Ancalagon — one run, end to end

The codebase is one class per module, which makes each file trivial to read and the
system harder to trace. This document follows a single run through every file it
touches, in order. Read it once and the layout stops being a maze.

The design rationale lives in
`docs/superpowers/specs/2026-08-02-ancalagon-agent-harness-design.md`. This is the map,
not the reasoning.

## The shape in one paragraph

Three kinds of process share no memory. A **CLI** writes a task to disk and hands it to a
**supervisor**, which spawns a **worker** per attempt. The worker runs one `Session` — the
agent loop — and writes its result back to disk. Nothing talks to anything else directly:
every hand-off is a SQLite row or a file.

```
cli.py ──writes spec.json──▶ tasks/root/
   │                              ▲
   │ enqueue                      │ outcome-<agent>.json
   ▼                              │
 bus.db ◀──claim──── supervisor ──┴──spawn──▶ worker ──▶ Session ──▶ llm ──▶ provider
                                                            │
                                                            └──▶ tools ──▶ files
```

## The trace

### 1. Starting a run — `ancalagon/cli.py`

`main(config_path, run_dir)`. The run directory is created by `ancalagon init` and migrated by
`ancalagon migrate` before this runs — three separate invocations, so that schema changes are
applied by the startup script rather than as a side effect of starting a run:

```bash
RUN_DIR=$(ancalagon init --config ancalagon.toml)
ancalagon migrate --db "$RUN_DIR/bus.db"
ancalagon run --config ancalagon.toml --run-dir "$RUN_DIR"
```

`init` allocates `<write_root>/runs/r_YYYYMMDD-HHMMSS`, stamped from the injected clock in UTC,
when `--run-dir` is absent, and creates the named
directory when it is given. A named directory is reused if present, which is what makes a second
invocation continue rather than start over; an allocated one must not already exist.

1. `config/load.py` reads the TOML. Relative roots resolve against the **config file**, not
   the process cwd, so a worker started elsewhere sees the same paths.
2. `bus.db` is opened before anything is written, so a run against an absent or out-of-date
   database refuses before creating a task directory.
3. `root_spec` builds the root's `AgentSpec` from `[run] role`, looked up in `config.roles` and
   embedded whole — not copied to disk, since the path in a role's `input`/`answer` `ClassRef`
   already names where the config says the contract module lives, and the worker resolves it
   there directly. The goal comes from `[run] goal_file` and nowhere else; the input comes from
   `[run] input_file` when set, validated against the role's input class, or is built as
   `{"text": goal}` when the role's input is `FreeText` and no `input_file` is given. `spec.json`
   is then just `root_spec(config).model_dump_json()`. An unset, missing or empty goal file, a
   role that `[run] role` names but `[roles.*]` does not declare, or an `input_file` that fails
   to validate against the role's input class, exits 2 before any spawn.
4. The task is enqueued with `parent_agent=0`. Enqueuing creates
   the task if new, adds an agent, and appends a `queued` event; a task retried later reuses
   the task row and adds another agent.
5. Constructs the `Supervisor` and calls `run_until_idle()`, then `shutdown()` in a
   `finally`.
6. Prints the root's newest agent's `outcome-<agent>.json`. Because that file is named for the
   attempt that wrote it, a run that dies without writing one exits 1 instead of reporting an
   earlier attempt's answer.

The CLI never spawns anything and never speaks to a model.

**Opening a bus never migrates it.** `LifecycleStore.open` requires a database that exists and is
already at the latest version, and raises otherwise, naming the command to run. Migrating is
`migrations.migrate_file`, reached only through the `migrate` command. Starting a run never
migrates anything:

```bash
ancalagon migrate --db ws/runs/r_20260822-121500/bus.db          # to the latest version
ancalagon migrate --db ws/runs/r_20260822-121500/bus.db --to 0   # or back down to a given one
```

The split matters because the two acts have different blast radii. Starting a run is a
deliberate act on a directory you named, so upgrading its schema is part of what you asked
for. Reading a run is not: every tool, watcher and delegate tool that merely opens the bus
would otherwise rewrite it, and there would be no way to look at an old run without changing
it. `LifecycleStore.open` is the one everything else uses, and it only ever reads.

There is one connection, not one store. `ancalagon/bus/connect.py` opens it, sets
`PRAGMA busy_timeout` and runs the schema-version check above, and two adapters share what it
returns. `LifecycleStore` (`ancalagon/bus/lifecycle_store.py`) owns `tasks`, `agents` and
`agent_events` — everything about what an agent is doing. `MeterStore`
(`ancalagon/bus/meter_store.py`) owns `model_calls` and sits behind the `Meter` protocol the
session already calls; recording what a call cost is a different concern from recording what
an agent did, so it is a different table behind a different port, not a second set of methods
on the same class.

There is a single migration, `001_init`, describing the schema as it stands today. The
project's answer to a schema change is to edit it in place, not to add a numbered migration
on top: run directories are disposable and no compatibility with an older schema is promised,
so there is nothing gained by preserving the steps that got here. Editing `001_init` breaks
existing run databases outright — they are not upgraded, they stop opening — and that is a
deliberate stance, not an oversight.

The downgrade path is just as blunt. `--to 0` runs `001_init.down.sql`, which drops every
table `001_init` created — `agent_events` among them — rather than removing only what a later
migration would have added. A parent recorded `idling` mid-run, and any child recorded
`collected`, lose those rows along with the rest of the log; there is nothing partial about
going down a version when there is only one.

### 2. Supervising — `ancalagon/supervisor/supervisor.py`

`LifecycleStore.snapshot()` is the only way anything reads lifecycle state. It runs three
queries — every task, every agent, every event — inside one deferred transaction, and folds
the result into a frozen `Snapshot` (`ancalagon/attempt/snapshot.py`) that resolves each
agent's whole history into its attempt once, rather than leaving every caller to fold it
again. Every scheduling rule reads that `Snapshot` and nothing else: `outstanding`,
`uncollected`, `live_children`, `active_for`, `unreaped`, `wakeable`, `newest_agent`,
`task_of`, `is_news`, `has_news` and `depth_of` are pure functions in `ancalagon/schedule/`,
none of which import `ancalagon.bus`.

Seven import-linter contracts in `pyproject.toml` hold the boundaries at the build rather than
at review:

| Contract | What it holds |
|---|---|
| Layers point downward | the package list, `cli` at the top and `env : fs` at the bottom |
| Sibling leaves are independent | `contracts`, `clock`, `env`, `fs` know nothing of each other |
| The sandbox knows the file system and nothing else of ours | `sandbox` ↛ `clock`, `contracts`, `env` |
| Tools that take a model's path go through the workspace | seven tool packages ↛ `ancalagon.fs` |
| Domain does not import adapters | `attempt`, `schedule` ↛ `bus` |
| SQL stays in the adapters | everything but `bus` and `migrations` ↛ `sqlite3`, `sqlalchemy` |
| The process is reached only by the adapters that own it | everything ↛ `os`, bar two named edges |

Two settings are load-bearing and were checked against this repository rather than assumed.
`include_external_packages` is what lets a contract forbid `sqlite3` or `os` at all; without it
the contract passes silently. `allow_indirect_imports` restricts a contract to direct imports,
which three of them need — without it `supervisor → bus → sqlalchemy` flags every orchestrator,
and `tool → workspace → fs` flags the route the workspace contract exists to permit.

`ancalagon.migrations`' absence from the SQL contract's source list is a decision, not an
oversight: it opens its own raw connection to run the `.sql` files, because it is the adapter
that creates the schema the others assume already exists. That absence is worth stating in
prose rather than leaving to the TOML alone — an earlier version of the contract listed only
the package directories and missed every top-level orchestrator module entirely,
`ancalagon.cli` among them, until a fresh proof of a real violation on `cli.py` caught the gap.
The same omission was later inherited by the `os` contract, drafted from the SQL contract's
sources, and would have left `bus` and `migrations` free to read the environment; they are
listed there.

**The file system is enforced by the type checker, not by a contract.** An import contract can
see that one module depends on another; it cannot see `path.read_text()`, which is a method
call on a value a module already holds. Python splits the two things `pathlib` does —
`PurePath` is string manipulation with no syscalls, and `Path` subclasses it and adds forty
methods, every one a syscall. The domain says `PurePath`, so the attribute does not exist there
and Pyright rejects the call at the line it is written. `pathlib.Path` appears in exactly one
file, `ancalagon/fs/real_file_system.py`, which takes a `PurePath` and constructs the `Path`.
`resolve` and `expanduser` are on the port for the same reason — both are syscalls — while
`.parent`, `.name` and `/` stay on `PurePath`, where they cost nothing.

`run_until_idle()` loops on `tick()`, which calls `snapshot()` exactly once, after starting
and reaping, so waking idled parents costs the same three reads regardless of how many tasks
or children exist — the cost that used to grow with both. A test pins that count with
`sqlite3`'s own trace callback, isolated to the wake path by leaving no concurrency free to
start queued agents, rather than trusting the design to hold as the code changes; a task graph
the size of a tree used to cost one query per task plus three per child, issued twenty times a
second. Starting and reaping issue their own reads on top of those three, scaling with how many
agents are claimed and how many processes are live.

- `_start_queued` claims a batch sized to the free concurrency — `bus.claim(limit=free)`, which
  appends `claimed` — and spawns each in turn. After spawning it appends `running` with the
  pid; a failed spawn appends `crashed` and reports to the parent.
- `_reap` polls each live process. One still running but past `agent_timeout_s` is killed and
  closed `timed_out`; one no longer running is closed `crashed`. Closing reads whatever the
  worker left on disk: if `outcome-<agent>.json` exists, the terminal row records that outcome's
  `kind` — the worker spoke, so its account is what gets written, even for a process the
  supervisor had to kill — and if it does not, the row records the close the supervisor
  itself observed. The exit code decides nothing; no terminal row records one.
- `_wake_idling` re-enqueues a task whose newest agent idled and has since had a child settle
  — `wakeable` evaluates that as a predicate over the tick's `Snapshot`, not as an event fired
  when a child finishes, and skips a task whose newest agent is still
  one of this supervisor's own live processes. A child is news only once its newest agent
  reaches `Closed` or `Lost`, and only the supervisor writes either: the worker records
  nothing about its own lifecycle at all, only `outcome-<agent>.json`, so waking on the worker's own
  word is not an option — there is no word to wake on. The predicate therefore reads the
  database alone — a watcher, or a second supervisor, gets the same answer. Re-enqueuing
  runs the parent again as a **new** agent against the same task, with a fresh copy of its
  role's `budget`: nothing carries over from the idled attempt but the transcript. A parent
  that idles waiting on three children may therefore spend four budgets across the run, not
  one.
- The loop exits when nothing is live and nothing is queued.
- Before the loop starts, `resolve_stale` takes its own `snapshot()` and settles what a
  previous supervisor left behind. `unreaped` finds agents whose attempt is `Claimed` or
  `Running` — spawned, or spoken for, but never closed. Deriving that from the whole history
  rather than from the latest row
  is what catches a worker that had already written `outcome-<agent>.json` before the previous
  supervisor stopped: its last row is still `running`, so nobody else has closed it yet. The
  recorded pid then decides what happens to it. A process still alive and inside its timeout
  is **adopted**, not abandoned: it is wrapped in an `AdoptedProcess` — a `Liveness` check
  standing in for the pipe an actually-spawned `Popen` would have — and put into `self.live`
  so it is reaped, closed and waited for like any other agent this supervisor started, with
  its timeout measured from when it actually started rather than from when it was adopted.
  One alive past its timeout is killed and closed `timed_out`, and one that is gone is closed
  `crashed` — both through the same read of `outcome-<agent>.json` that `_reap` uses, so a worker that
  managed to write its answer before the previous supervisor died is still `Closed`, not
  `Lost`. `shutdown` writes nothing at all — a supervisor that stops leaves its rows for the
  next one to settle.

  `max_concurrent` bounds what a supervisor **starts**, not what it holds: an adopted agent
  does not occupy one of its spawn slots, and adoption is never refused because the cap is
  already full. The cap exists to bound how much a supervisor sets in motion at once; a
  process that is already running was set in motion by somebody else.

Nothing is ever updated: every status is a new row, so an agent's whole history survives.
Only the supervisor ever writes a row about an agent's own lifecycle, and it writes exactly
one terminal row per agent — carrying both that the process ended and what the worker said,
when the worker said anything — which is why there is nothing left to reconcile against
`outcome-<agent>.json`: the terminal row was read from it.

That holds for the whole schema, not just this table. There is no row anywhere in `bus.db`
that is written twice: current state is *derived* by folding an agent's whole history, so
`claim` appends a `claimed` event rather than setting a flag. A parent learns what happened
to a child the same way everything else does — by reading its events and its
`outcome-<agent>.json`, through `check_task` and `collect_task`. There is no notification to
deliver and no cursor to advance. `collect_task` appends a `collected` event to a closed
child's newest agent, so a parent reading its answer is itself a fact in the log, not
something inferred from the parent's own behaviour afterwards. A `Collected` attempt is
finished, so it does not read as active to `active_for`, which is what lets the same task be
answered or re-delegated afterwards.

## The lifecycle

An agent's events are not a log the code reads selectively. `ancalagon/attempt/` folds them
into exactly one state: `Nascent` before anything is written, then `Queued`, `Claimed`,
`Running`, and finally `Closed`, `Lost` or `Collected` — seven states, one fold, no others.

Only the worker writes `outcome-<agent>.json`, and only the supervisor writes an agent's terminal
row, so the state that row lands in is decided by whether the worker got to write first.
`Closed` means an answer exists on disk; `Lost` means it does not. That holds by
construction, not by convention: `_close` in the supervisor checks for `outcome-<agent>.json` before
every terminal write, and there is nowhere else in the codebase that produces one. A worker
that caught an exception and still managed to write its outcome is `Closed(failed)`, never
`Lost` — `Lost` is for an attempt that never got to leave anything behind at all, killed on
a timeout or gone before it could write, whichever the supervisor observed. `Collected`
carries which of the two its parent read.

The axis that separates a spoken verdict from a silent close is carried by the **status
alone**. `source` no longer varies for an agent's own lifecycle — every row about what
happened to an agent, from `queued` through to `closed`, is the supervisor's; the worker's
only remaining bus writes concern *other* agents, appending `collected` when it reads a
child's answer and `queued` when it spawns one. A `Closed` row's status is the worker's own
word — `completed`, `exhausted`, `failed`, `needs_input` or `idling` — carried into the
terminal row exactly as the worker left it; `exited` is not a status anything writes. A
`Lost` row's status is `crashed` or `timed_out`, the supervisor's own observation. Every
predicate — `outstanding`, `uncollected`, `unreaped`, `active_for` — reads the fold instead
of the latest row, but for an agent's own lifecycle the fold and the latest row now agree,
because nothing writes over what the terminal row already said.

`next_state` is the single transition table and `attempt_of` is a fold over it, so the
lifecycle has one definition rather than one per caller. `LifecycleStore.record` is where it is
enforced: it derives the current attempt, asks `next_state`, and refuses an illegal write
with `IllegalTransition` naming the state, the status and the source. `queued` is legal only
from `Nascent`, `claimed` only from `Queued`, `running` only from `Claimed` — a finished
attempt cannot be claimed a second time. `enqueue` and `claim` write through a private
variant that assumes the transaction they already hold, so exactly one place owns a
transaction on every path.

One consequence is worth stating plainly, because it changes what a parent can do:
`collect_task` requires a child to be `Closed` or `Lost` before it will read the answer, and
fails with "has not been closed yet" otherwise. A parent can no longer collect from a child
whose process is still exiting. It reads the bus, not the filesystem, to decide this — a
`Lost` child never gets an `outcome-<agent>.json` to read, so `collect_task` reports it straight from
the summary on the event that closed it, and a `Closed` one is read from disk as before.

It never retries. A crash is reported; the parent decides.

`subprocess_spawner.py` is the only module that constructs a process. `process.py` and
`spawner.py` are protocols so the supervisor can be tested without launching interpreters. It
holds three ports of its own — a `Sandbox`, an `Environment` and a `FileSystem` — and nothing it
needs comes from the ambient process.

It wraps the command it builds with an injected `Sandbox` (`ancalagon/sandbox/sandbox.py`)
before spawning: `Fence` writes its policy as `fence.json` into the run directory, so a run
records what it ran under, and prepends `fence -s <policy> --`; `Unsandboxed` returns the
command unchanged. The sandbox confines writes to `write_root` but leaves reads unrestricted
— fence cannot express "deny everything except the roots" without also denying the roots
themselves, as `docs/superpowers/specs/2026-08-16-sandbox-mode-design.md` shows. On macOS,
fence also grants an implicit write carve-out for the whole `$TMPDIR` tree independent of the
policy — a known limitation, recorded there rather than fixed.

Network traffic leaves through fence's own proxies, which it advertises to the child by
setting `ALL_PROXY` to a SOCKS5 endpoint and `HTTP_PROXY`/`HTTPS_PROXY` to an HTTP one. It
overwrites all four proxy variables, and `no_proxy` with them, whatever the parent passed —
so `Sandbox.environment()` cannot influence them and the project depends on `httpx[socks]`
instead, which is what lets litellm use the SOCKS endpoint fence prefers. The spec's claim
that clearing `no_proxy` from the parent fixes loopback does not hold for that reason.

What a child inherits is a value the harness chose, not whatever the launching shell held.
`inherited(environment, sandbox)` merges an `Environment` (`ancalagon/env/`) with the sandbox's
overrides, and it is a plain function so a test can assert what a child would get without
spawning one. `os.environ` is read in exactly one place, `env/real_environment.py`, and an
import contract forbids `os` everywhere else bar `os_liveness`, which needs `os.kill`. The
motivating case was narrow but real: with `GIT_DIR` exported — which is what `git` does when it
runs a hook — `git -C <dir> log` inside a tool reads the wrong repository. Nothing launches the
harness from a hook today, so this closes a propagation path rather than a live bug.

`clock/` holds the last: one `Clock`, with `now()` for the instant a row or a message is
stamped with and `time()`/`sleep()` for how long an agent has been running. The supervisor,
the bus and the session all take one, defaulting to `SystemClock`, so no timestamp anywhere
comes from calling `datetime.now` in place. `FakeClock` starts at a fixed instant and moves
only when slept, which is what lets a test assert what a transcript or an event log says
rather than merely that it says something.

### 3. One attempt — `ancalagon/worker.py`

Invoked as `python -m ancalagon.worker --run-dir … --dir … --agent-id … --config …`.

`main` opens the transcript **first**, so even a failure mid-setup leaves a record, then:

1. Reads `spec.json` as `TaskSpec` — `task_id`, `role: Role` and `goal`, the scalars and the
   whole role, since the `input`'s class is named by the role itself and so cannot be known
   before reading it.
2. `contracts/resolve.py` takes the role's `answer` and `input` — each a `ClassRef`, a module
   *path* and a class name — imports that module from the path the config named when the role
   was declared, and returns each class. Nothing is copied and nothing is defended against: the
   path comes from configuration, not from a model, so there is no directory to contain it
   inside. The spec is then re-read as `AgentSpec[input_class]`, so the `Session` is handed a
   validated model rather than text.

   The cost is provenance, not correctness: a run no longer freezes the *shapes* it ran under,
   only the `ClassRef` naming where to find them. Editing the module a role's contract points at
   between a run and its resumption silently changes the contract later agents work to — the
   config file is the record, and a mid-run edit is the operator's problem.
3. If a `transcript.jsonl` already exists, `transcript/history.py` loads and **repairs** it:
   a transcript ending in an unanswered tool call is rejected by the API, so interrupted
   calls get synthetic error results. This is the whole of resumption — there is no
   "resume mode".
4. Builds the registry, which is the only thing the `Session` is given: it holds no reference
   to any tool.
5. Runs the session and writes its outcome to `outcome-<agent>.json`, then returns 0.

A worker records nothing to the bus about its own lifecycle — `outcome-<agent>.json` is the whole of
what it leaves behind about how it ended. The supervisor is the only writer of an agent's
terminal row, and it reads that file to decide what to write in it, which is what keeps the
row and the file from ever disagreeing.

Any exception writes a `Failed` outcome carrying the traceback and returns 1, so a task is
never left uncollectable. This is the one catch-all in the codebase and it is deliberate: it
is the outermost frame of a process, and a worker that dies without an `outcome-<agent>.json` is
indistinguishable to `collect_task` from one still working, for ever.

`build_registry` decides which tools an agent's registry can serve at all, not which of them
it is offered on a given turn: the role's own `tools` filters the list, every `delegate_<name>`
entry is withheld once `bus/depth_of.py` reports the task is at `max_depth`, and `submit_answer`
and `idle` are both added unconditionally, regardless of what `tools` names — a role author who
left either out never chose to crash the harness, or to spawn children it could never wait for.
A name in `tools` that no tool answers to raises, naming both the unknown entries and the
available set. An empty `tools` list now means no tools at all, the inverse of the old global
`[tools] enabled = []`, which meant every tool — a role written against the old default gets a
much smaller toolset than its author expects, silently, unless `tools` is filled in.

Which of `idle` and `submit_answer` the model actually sees changes every turn. `Session`
learns the facts it needs through an injected `Children` port (`ancalagon/children/`) —
`outstanding()` and `uncollected()`, both tuples of agent ids — rather than deciding once at
registry build time: `_declarations` offers `idle` while `outstanding()` is non-empty, and
`submit_answer` once both `outstanding()` and `uncollected()` are empty, or unconditionally on
the turn the budget runs out. `BusChildren` answers both from the bus; `NoChildren` /
`NO_CHILDREN` is the null object for an agent with no `delegate_<role>` tool at all, so the
check costs nothing where it can never apply.

### 4. The loop — `ancalagon/session.py`

`run()` is the centre of the system:

```
while True:
    final = out of turns
    outstanding = children.outstanding()
    final and outstanding? ─────────▶ Idling  (turns ran out while children were still working)
    declare idle / submit_answer per outstanding() and uncollected(), or submit_answer only if final
    final? record FINAL_INSTRUCTION
    reply = llm.complete(_system(), messages, schemas, forcing submit_answer if final)
    record it
    did it call tools?
        yes ─▶ _run_tools()
               idle called?              ──▶ Idling
               need_input.question set?  ──▶ NeedsInput
               submit.answer set?        ──▶ Completed, or Exhausted if final
               loop
        no  ─▶ parse the text as the output class
               valid?   ──▶ Completed, or Exhausted if final
               invalid? ──▶ tell it so and loop, or Failed if final
```

There is no separate final-turn code path any more — the last turn is this same loop with two
flags set, `final` and `force_tool`. Five things worth knowing:

- **The run ends in one of four places.** Before the model is even called, if the turn budget
  is exhausted while a child is still outstanding (`Idling`, spending no turn at all). Through
  a tool result — `idle`, `need_input` or `submit_answer` — whose `ToolResult` carries an
  `Idled`, an `Asked` or a `Submitted` payload that `_run_tools` hands back for `run` to read.
  No tool holds state, and the session holds no second reference to one — the ending travels
  along the call it came from. Or by parsing the reply's raw text as the output class, when it
  called no tool at all.
- **`_run_tools` refuses calls past the budget** rather than letting it go negative, and
  returns the refusal to the model as an error result.
- **A tool called with bad arguments is caught** and becomes an error result, so the model
  reads its own mistake and corrects it. Only `pydantic.ValidationError` is caught, which is
  what `bind_tool` raises when the model's JSON does not match the tool's args model. Anything
  else a tool raises is a defect rather than a move the model made, and it propagates to the
  worker, where it becomes a `Failed` outcome carrying the traceback — visible, rather than
  handed back as a tool error the agent burns turns retrying against.
- **The final turn is forced, not merely offered.** `_prepare_final_turn` records
  `FINAL_INSTRUCTION`, injecting a synthetic assistant turn first if the last message was a
  user turn — providers reject two consecutive user turns — and `_complete` is called with
  `force_tool="submit_answer"`. `_declarations` also collapses to `submit_answer` alone on
  that turn, offered regardless of whether every child has been collected: being cut off by
  the budget is not the same as choosing to skip reading a child's answer.
- **`_system()` returns two halves**, `SystemPrompt(static, per_item)`: behaviour and answer
  instructions, identical for every item in a population, then this item's goal, input and
  scopes. Only the static half is cache-marked, so the cached prefix is shared across items.
  Each turn logs the cache counters the provider returns, which is the evidence it worked.
- **Every completion is metered.** `_complete` hands the reply's `CallUsage` to a `Meter`
  before logging it. `Meter` is a Protocol with one method, so the session neither knows nor
  cares where the numbers go; the worker passes `BusMeter`, which appends a `model_calls`
  row, and the default is `Unmetered`, which discards them. A `Session` built in a test or a
  library caller therefore records nothing until someone asks it to.

### 5. Calling a tool — `ancalagon/tools/`

`Tool` is generic in its arguments: `Ripgrep` is a `Tool[GrepArgs]` and its `run` takes a
`GrepArgs`. **No tool ever sees a string.**

The registry cannot hold those directly. `run` consumes its argument, so the parameter is
contravariant and `Tool[GrepArgs]` is not a `Tool[BaseModel]`; a mixed list has no element
type to name. Enumerating them as a union fails too, because `submit_answer`'s model and each
`delegate_<role>`'s model are resolved per role at worker startup — known only once the config
and the spec are read, not at authoring time — and a union has to name its members up front.

`registry/bind_tool.py` resolves it. It is a **generic function**, so inside it `ArgsT` is
one concrete type — `args_model.model_validate_json(text)` returns exactly what `run`
accepts — and it returns a non-generic `BoundTool` holding a closure. The type parameter
lives in a scope instead of in a field, which is the one place it can live. That closure is
the single site where a tool call's JSON text becomes a model; there were twenty-one before.

A malformed argument therefore raises inside `invoke`, and `_run_tools` turns it into an
error result the model reads and corrects — identically for every tool, including
`submit_answer`, which used to catch its own.

Each tool then:

1. Receives its arguments already validated. A constraint belongs on the args model rather
   than in `run`: `schema_of` builds the tool schema from that same model, so a `pattern`, a
   `default` and a `description` are shown to the model before it calls, while a hand-rolled
   check in `run` can only report after it has. The two
   are not equivalent — `delegate`'s `answer_schema` was checked in `run` and the model,
   seeing a bare string, guessed wrong six times in one turn. It was called `output` then,
   which is most of why: it names the class a child must answer in, and a field called
   `output` invites a model to describe a kind of output instead. It answered `"text"`.
2. Reaches the file through `workspace/workspace.py`, which resolves first and then checks
   containment, so `..` and symlinks are handled by the same check. `Workspace` used to be a
   path *authority*: `resolve_read` answered "may I touch this" and handed back a path the
   tool then read itself, which made scoping a convention each of the seventeen tools
   re-enacted rather than an invariant. It now holds a `FileSystem` and exposes the operations
   the tools use, each resolving before it delegates, so reading is only reachable through the
   scoped method. `resolve_read` and `resolve_write` stay public because `ripgrep`, `ast_grep`,
   `find_symbol` and `code_stats` need the resolved path as a string for a subprocess rather
   than its contents. An import contract keeps the seven tool packages that act on
   model-supplied paths from importing `ancalagon.fs` at all; the delegate tools and `idle`
   hold the port directly, because they work on `run_dir` paths the harness built.
3. Writes its full output to a file under the task's `tools/` directory and returns a
   `ToolResult` carrying that path and a **`Payload`** — a model, not a string. `TextAnswer`
   is the ordinary one and renders to exactly the text the tool produced, so a ripgrep result
   still reaches the model as `path:line:text`. `Submitted` carries the validated answer and
   `Asked` the question, which is how the session recognises an ending: `isinstance` on the
   payload, with no tool state to read and no name to match. Rendering is
   `payload.text_for_model()`, so each type decides how it reads rather than the session
   branching on which it got. That write goes through
   `resolve_write` like any other, so the same roots bound a tool's own output as bound
   what it was allowed to read — and the check happens before the directory is created, so
   a context pointed outside the write root leaves nothing behind. A `ScopeError` here is a
   misconfigured context rather than a model mistake, so it propagates to the worker and
   becomes a `Failed` outcome; turning it into a `ToolResult` is impossible anyway, since
   reporting a failure is itself a write.

A tool that shells out has a fourth obligation: **a model-supplied string never reaches
argv where the child would read it as an option.** `ripgrep` and `sed` pass theirs behind
`-e` and terminate options with `--`; `query_json` and `git_history` refuse a leading dash
at the boundary instead, because a jq filter and a git rev have no legitimate reason to
begin with one, while a regex does. Without this, `rg --pre=<cmd>` is arbitrary execution
outside every root the workspace declares.

The session puts the summary and the path into the tool result the model sees. Large output
never enters the context; the model reads it with `read_file` if it wants to.

`parse/ast_query.py` is the structural counterpart to `ripgrep`. It runs a tree-sitter query —
an S-expression whose parts are named with `@` — and returns one record per match, each named
capture carrying its node type, byte range, row and column, and its text. Where `ast_grep`
answers *does this shape occur*, a query answers *where is each part of it*, which is what a
caller wanting to cite a location rather than read one needs. `parse/languages.py` is the one
place a grammar is named, so `treesitter` and `ast_query` support the same set: Python and Java.
A query the grammar rejects comes back as a failed result carrying tree-sitter's own message.

A role may wrap any tool it uses with **hooks**, declared under `[roles.*.before]` and
`[roles.*.after]` and resolved by `registry/bound_for.py` where the tool's own `args_model` is in
hand. A hook is a stateless function returning `Accepted` with the value to go on with — the same
one or a modified one — or `Refused` with what the agent is told. `bind_tool` runs them around
`run`, so a refusal becomes an ordinary failed `ToolResult` and the session's existing path
applies unchanged: the agent reads the reason on its next turn and tries again, exactly as it
does for a malformed argument.

Two checks make that safe. `isinstance(given, tool.args_model)` narrows a `before` hook's output
back to the tool's argument type, and catches a hook that returned some other model rather than
handing it to `run`. And `registry/accepts.py` reads the declared type of a hook's first
parameter and requires `issubclass(args_model, declared)`. A hook written for `sed` therefore
cannot be attached to `ripgrep`, while one declared over `BaseModel` may be attached to anything,
and either way the fault is found before any agent starts. `check_contracts`
builds every role's registry for that reason, so a bad hook exits 2 naming the role.

`ToolContext` carries the task's input, which is what lets a hook check an answer against what
was asked. An `after` hook cannot undo a side effect — it runs after `run`, so prevention belongs
in `before` — but `submit_answer` has none to undo: its hook runs long before the worker writes
`outcome-<agent>.json`, so an answer can be refused or rewritten with nothing to reverse. A
refusal on the forced final turn ends the attempt `Failed` naming the refusal, since a check is a
hard gate and an answer that never satisfied it is not an answer.

`shell/shell.py` is the one deliberate exception to that obligation. It takes a command line and
hands it to `/bin/sh`, so pipes, globs and substitution work and nothing about the command is
inspectable before it executes. What bounds it is not the argument but the sandbox — `Fence`
allows writes only to `write_root` and `run_dir`, and network only to `allowed_domains` — and
the directory it runs in, which is a **required** argument resolved through
`Workspace.resolve_read` like any other path. Without it the command would inherit the worker's
own `cwd`, which is the run directory, and an agent searching `.` would find its own
transcripts. It is killed after `TIMEOUT_S` seconds and a hang comes back as an ordinary failed
tool result, rather than blocking until `agent_timeout_s` takes the whole attempt down. Under
`Unsandboxed` nothing bounds it at all.

`submit/submit_answer.py` and `need_input/need_input.py` are the two tools whose results the
session reads.

There is no `delegate` tool any more — there is one `delegate_<role>` per role declared in the
config, built by `delegate_tools` (`ancalagon/tools/delegate/delegate_tools.py`) at worker
startup, each a `DelegateTo` bound with that role already closed over. A parent does not grant
a child whatever it asks for and cannot be wrong about the grant: `DelegateTo` writes the
*role's* `budget` into the child's `spec.json` unchanged, so a parent with 8 turns left may
still spawn a 20-turn child. Total work across a run is therefore bounded by the role graph and
`max_depth`, not by the root's own budget — the config author's business, not the harness's.
A role naming no `delegate_<x>` tool cannot spawn at all. `need_input` is a **yield, not a dead end**: the agent stops, its question and its
whole transcript stay on disk, and `answer.py` appends the answer as a user message and
enqueues the task again. Resumption then does the rest, since a worker loads whatever
transcript is already in its directory. Nothing blocks and no channel is held open —
answering is a write and a row, like everything else here.

Both `answer_task` (a parent answering its child, mid-run) and `ancalagon answer` (you
answering the root, after the run) call the same function. They matter at different moments:
a run is autonomous, so by the time a person could read a child's question the parent has
long since decided. A parent that cannot answer calls `need_input` itself, which carries the
question up to the root and out to you; your answer then flows back down. Questions bubble
up, answers flow down, and the machinery is one append and one enqueue.

Answering refuses unless the agent's history **contains** a `needs_input` event and its task
has no live agent, so a question cannot be answered twice into two competing resumptions.
`delegate_to.py` writes a child's `spec.json` and enqueues it — it does not spawn; the
supervisor does.

### 6. Talking to a provider — `ancalagon/llm/`

`llm.py` is the only seam between the loop and any provider. `fake_llm.py` implements it
with scripted replies, which is what makes the entire loop testable offline.

`adapters/litellm_client.py` carries `num_retries` and `timeout` from config, so a transient 429 or 5xx is retried rather than killing the task. It translates in both directions: our `Message` objects become
`wire_message.py` models dumped to OpenAI-shaped dicts, and the response becomes `Text` and
`ToolUse` blocks. The `adapters/` directory is quarantined in `pyrightconfig.json` — it is
the only place third-party type gaps are tolerated.

## What a run leaves behind

```
ws/runs/r_20260822-121500/
    bus.db                        tasks, agents, every event about them, every model call
    tasks/root/
        spec.json                 what was asked, with the whole role embedded
        transcript.jsonl          every message, one per line, tagged by agent id
        outcome-<agent>.json      the result of that attempt, kept even when superseded
        stderr-1.log              the worker's stderr
        tools/0000-read_file.txt  every tool's full output
    tasks/<child>/                same shape, one per delegated task
```

Because the transcript is flushed per message, a run is watchable while it happens:

```bash
tail -f ws/runs/r_20260822-121500/tasks/root/transcript.jsonl
```

Everything is inspectable without ancalagon:

```bash
sqlite3 ws/runs/r_20260822-121500/bus.db \
  "select agent, status, source, summary from agent_events order by id"
sqlite3 ws/runs/r_20260822-121500/bus.db \
  "select agent, count(*), sum(prompt_tokens), sum(cache_read_tokens)
   from model_calls group by agent"
rg '"agent": 1' ws/runs/r_20260822-121500/tasks/root/transcript.jsonl
```

There is no `ancalagon usage` verb — the schema is the query surface, and `MeterStore.calls` and
`MeterStore.tokens_by_agent` are the same two queries for callers already holding a bus.

Two commands do read a finished run, and they are split so that neither decides for the other.
`trace` (`ancalagon/trace_command.py`) takes a `Snapshot` and each task's transcript and folds
them into a `Trace` — `{nodes, edges}`, where a node is a task, an agent attempt or a tool call,
and an edge is `spawned`, `woke`, `called`, `delegated` or `collected`, each carrying the
timestamp it happened at. It emits that as JSON. `viz` (`ancalagon/viz_command.py`) parses the
same JSON back into a `Trace` and renders a Mermaid sequence diagram, one lane per task. Neither
writes into the run directory, and a different renderer reads the same file.

`graph_of` is pure — a `Snapshot` and a mapping of messages in, a `Trace` out — which is why the
whole fold is tested without a database. Delegation is read from `tasks.parent_agent` rather than
from a tool's arguments, since the bus already records which agent enqueued a task; collection is
the one edge that needs an argument, and `TaskArgs` parses it.

## Where to start reading

| Question | File |
|---|---|
| How does an agent turn work? | `session.py` |
| What can an agent do? | `worker.py`, `build_registry` |
| How does work get scheduled? | `supervisor/supervisor.py` |
| What crosses a boundary? | `contracts/` |
| How is a provider called? | `llm/adapters/litellm_client.py` |
| What stops an agent escaping? | `workspace/workspace.py` |
| What may touch a file at all? | `fs/real_file_system.py`, and the contracts in `pyproject.toml` |
| What happened in a run I already have? | `trace/graph_of.py`, and `viz/mermaid.py` to draw it |
