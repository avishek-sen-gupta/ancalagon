# Ancalagon

An agent harness for reverse engineering.

## What it does

Give it a goal. An agent pursues it with tools — ripgrep, ast-grep, tree-sitter,
stream-only sed, scoped file access — and delegates focused subtasks to isolated
subagent processes, each with its own budget and its own typed output contract.

A goal is all it needs. Point `read_roots` at whatever the agent should be able to
read — a repository, a directory of parsed artifacts, a single JSON file, or nothing
at all — and it stays inside that boundary.

Subagents return typed results. A child's shape is not invented by its parent at
runtime — it comes from a role declared in the config before the run starts, so a
fan-out produces structured data because the contract was decided up front, not
guessed at mid-run.

## Running

```bash
uv sync
cp ancalagon.example.toml ancalagon.toml   # edit write_root, read_roots and goal_file
echo "..." > goal.md
RUN_DIR=$(uv run ancalagon init --config ancalagon.toml)
uv run ancalagon migrate --db "$RUN_DIR/bus.db"
uv run ancalagon run --config ancalagon.toml --run-dir "$RUN_DIR"
```

`scripts/ancrun.zsh <config.toml> [run-dir]` does all three; run it with no run directory to
allocate a fresh one, or pass an existing one to continue that run. Those three steps are the
startup script. `init` allocates `<write_root>/runs/r_YYYYMMDD-HHMMSS` from the UTC clock and
prints it, or creates and prints the directory given to `--run-dir`. `migrate` brings that run's
database to the latest schema, creating it on a fresh directory. `run` never creates or
upgrades a database: it refuses one that is absent or out of date and names the command to
fix it.

Everything an agent is — its behaviour, what it is told, what shape it must answer in, its
tools, its budget — is a **role**, declared under `[roles.*]` and never authored at runtime:

```toml
[roles.root]
behaviour = "You investigate a codebase or a set of artifacts to answer the goal you are given."
tools = ["read_file", "ripgrep", "ast_grep", "list_dir", "delegate_component_analyst"]
budget = { turns = 20, tool_calls = 60 }

[roles.component_analyst]
behaviour = "Read before concluding. Cite the files you read."
input  = { module = "./shapes.py", name = "ComponentQuery" }
answer = { module = "./shapes.py", name = "Component" }
tools  = ["read_file", "ripgrep", "find_symbol"]
budget = { turns = 12, tool_calls = 30 }
```

Omitting `input` or `answer` means `FreeText` — that is how a role opts into prose instead of
naming a path. A role that names no contract gets none; there is no default global budget or
tool list, only what each role states. A role a worker may spawn gets a `delegate_<role>` tool,
built at worker startup from that role's own input contract, so a parent sees the child's real
input schema rather than a string it has to guess the shape of. A worker builds those tools for
the roles its own `tools` list names, so it never loads the contracts of roles it cannot spawn.
A role name becomes a tool name, so it must be a Python identifier.

The root is a role like any other. `[run] role` names which one it runs as, and its goal and
input come from files rather than from a `delegate` call, since it has no parent to call one:

```toml
[run]
goal_file = "./goal.md"
input_file = ""                  # validated against the root role's input class; empty + FreeText means {"text": goal}
role = "root"
```

A run directory is named on the command line, never in the TOML. Passing the same one to a
second invocation continues that run rather than starting over. An unset, missing or empty `goal_file`
exits 2 without starting a run, and so does `[run] role` naming a role `[roles.*]` does not
declare. Every declared role's `input` and `answer` are resolved before the run starts too, so
a contract module that does not parse or does not exist exits 2 naming the role and the path,
rather than crashing a worker later.

`tools` is per role, and it is a change of default from the version before roles existed: an
empty list now means *no tools*, not all of them. Every tool a role may use must be named,
except `submit_answer` and `idle`, which every role gets regardless of its `tools` list — the
session decides per turn which of the two to offer, and forces `submit_answer` on the turn its
budget runs out, so an author who forgot to list either would only produce a harness crash, or
a delegating agent that can never wait for its own children, not a deliberately toolless agent.

The harness does not check that a role graph makes sense. A role holding `delegate_x` but not
`collect_task` can spawn children whose answers it can never read — and because `submit_answer`
is withheld until every child is collected, such a role can never answer while turns remain
either; it always runs its whole budget out and finishes `Exhausted`, never `Completed`. A role
whose children call `need_input`, but which itself lacks `answer_task`, leaves them waiting
until they time out. Getting the pairing right is the config author's job.

A parent with children still working is not left polling to learn when they finish. Each turn
it is offered `idle` in place of `submit_answer` while any child is outstanding; calling it
ends the attempt with an `Idling` outcome and the process exits, its transcript and event log
left on disk. The supervisor re-enqueues the task once a child settles after the parent idled,
and the run resumes as a **new** agent against the same task — with a fresh copy of its role's
`budget`, since a resumed agent starts fresh like any other. A parent that idles waiting on
three children may spend four budgets across the run, not one; that cost lands on whichever
role the parent is, so it belongs in the same place as any other budget decision. `check_task`
still reports a child's status without waiting or spending a turn; `collect_task` reads its
answer once the supervisor has closed the child, and records that the answer was read — a
child whose process is still exiting is not yet collectable, and says so. A child the
supervisor had to kill is collectable too: `collect_task` reads that outcome from the bus
event that closed it rather than from a file that was never written. `submit_answer` stays
withheld until every child
is both settled and read, except on the turn the parent's own budget runs out, when it is
offered regardless — being cut off is not a choice to skip reading what was commissioned.

A `spec.json` embeds the whole role as it was when the task was queued, not a name pointing
into the config, so an edit to `[roles.*]` affects only tasks queued afterwards — a config
change mid-run cannot silently redefine a task already sitting in the bus. That freeze is not
total: a frozen role naming `delegate_x` still fails on resume if role `x` is later removed
from the config, and the contract *source* is never frozen, since `{module = "./shapes.py"}`
is a path — editing that file changes the shape a resumed run works to, even though the role
itself did not change.

`load_config` reads every field it needs by name, so a config missing one fails loudly. It
never validates the whole document, though, so a config left over from before roles existed —
a stray `[agent]`, `[tools]` or `[budget]` section — loads silently and is simply ignored.
Upgrading a config means deleting those sections yourself; nothing will tell you they are
dead weight.

Keep a named run directory under `<write_root>/runs/` as above: the watcher below only sees
`<write_root>/runs/*/tasks/*` and `<write_root>/*/tasks/*`, and a run elsewhere is invisible to it.

Watch a run as it happens, including subagents spawned mid-run:

```bash
./scripts/ancwatch.zsh ancalagon.toml    # start before or during a run
```

Give it the same config the run uses and it watches that config's `write_root`, so
the two cannot disagree about where runs live. A directory works too.

On Bedrock with a bearer token, `scripts/ancrun.zsh` runs the same command with stale AWS
credentials stripped from the environment — otherwise litellm signs with those instead and
Bedrock rejects the request. It reads `AWS_BEARER_TOKEN_BEDROCK` from the environment and
refuses to start without it.

Runs are sandboxed by default: every worker process is wrapped with `fence`, so `fence` must
be installed (`brew install fencesandbox/fence/fence` or see the project's own instructions).
Set `[sandbox] strategy = "none"` in the config to run unsandboxed instead. The sandbox
confines writes to `write_root`; it does not restrict reads, so a sandboxed agent can still
read anything the user running it can. On macOS, fence also grants an implicit write
carve-out for the whole `$TMPDIR` tree regardless of the policy — a known limitation, not
enforced by us.

`run` brings its own run database up to the latest schema before opening it, so an existing
run directory keeps working after an upgrade. Nothing else migrates: opening a bus to read
one requires it to be current already. To upgrade a database without starting a run:

```bash
ancalagon migrate --db ws/runs/r_20260822-121500/bus.db          # to the latest version
ancalagon migrate --db ws/runs/r_20260822-121500/bus.db --to 0   # or back down to a given one
```

`--to 0` drops every table the schema creates, not just what a later migration would have
added — there is only the one migration. A parent's `idling` row and a child's `collected`
row go with the rest of `agent_events`, so a downgraded database loses the record of why a
parent stopped, along with everything else.

Only the worker writes `outcome-<agent>.json`, and only the supervisor writes a row about what
happened to an agent — one terminal row per agent, carrying the worker's own account when
there is one on disk to read, or the supervisor's own observation when there is not. That
single write is what an agent's rows mean: `Closed` if an answer exists, `Lost` if it does
not, decided the same way every time rather than assumed from whichever row is newest.
`LifecycleStore.record` enforces the order regardless, refusing to write a transition the lifecycle does
not allow, so a sequence that could not have happened is caught where it is written rather
than later, by whichever predicate first disagrees with it. `docs/architecture.md` has the
states and the reasoning.

## How it works

Three kinds of process, communicating only through SQLite rows and files:

- **Root agent** — reasons, uses tools, delegates.
- **Supervisor** — spawns, reaps, kills on timeout. Never retries; a crash is
  reported and the parent decides. The only module that constructs `Popen`.
- **Worker** — one agent session per process, one attempt at one task.

There is no IPC. A parent writes `spec.json` and enqueues a row; a worker writes
`outcome-<agent>.json` and `transcript.jsonl`. A subagent that needs input returns
`NeedsInput` and stops rather than asking mid-run, so nothing blocks and a dead
child cannot hang its parent.

Stopping is not giving up. Answer it and it continues from where it left off, with
everything it had already worked out:

```bash
ancalagon answer --run-dir ws/runs/r_20260822-121500 --task 1 --answer "keep both captions"
ancalagon run --config ancalagon.toml --run-dir ws/runs/r_20260822-121500   # same run dir; picks it up
```

A parent can do the same to its own child mid-run with the `answer_task` tool, and a
parent that cannot answer passes the question up by asking one itself. Meanwhile the
other children keep working — so by the time you answer, their results are waiting.

## Inspecting a run

Everything is on disk and in one SQLite file:

```bash
sqlite3 ws/runs/r_20260822-121500/bus.db \
  "select agent, status, source, summary from agent_events order by id"
rg '"agent": 17' ws/runs/r_20260822-121500/tasks/*/transcript.jsonl
```

Every model call is recorded too, so a run can be asked what it consumed and
which agent consumed it. That table has its own store, `MeterStore`, behind the
`Meter` a session calls — a separate concern from the agent lifecycle rows above,
sharing the run's one connection rather than a second database:

```bash
sqlite3 -json ws/runs/r_20260822-121500/bus.db \
  "select agent, model, sum(prompt_tokens), sum(completion_tokens),
          sum(cache_creation_tokens), sum(cache_read_tokens)
   from model_calls group by agent"
```

Tokens are recorded; money is not. Cost needs a price list that changes without
notice, and a figure computed at one week's prices is silently wrong the next.
The counters are facts the provider reported; pricing them is the caller's job.

Transcripts are appended and flushed per message, so a killed agent leaves a
readable partial history — which is what makes resumption possible.

## Layout

```
ws/runs/<run>/
    bus.db                        tasks, agents, an append-only event log, model calls
    tasks/<task_id>/
        spec.json  outcome-<agent>.json  transcript.jsonl  stderr-<agent>.log  tools/
```

Resumption is not a mode: a worker loads whatever transcript is already in its
directory. Point it at an existing directory to continue with history; give it a
new directory with the same spec for a clean retry.

## Constraints

Pyright strict with no `Any`, no `object`, and no JSON-blob types — JSON is text
until `model_validate_json` makes it a concrete model. One class per module.
No comments beyond a one-line header. See `CLAUDE.md`.

## Testing

```bash
uv run pytest tests/unit          # no network
uv run pytest tests/integration   # spawns real worker subprocesses
ANCALAGON_LIVE=1 uv run pytest tests/integration            # also calls a real model
ANCALAGON_LOCAL_MODEL=ollama_chat/qwen2.5:14b uv run pytest tests/integration
```

The integration suite's offline tests exercise the whole pipeline — CLI, bus,
supervisor, worker subprocess, outcome and stderr capture — without a credential.
`tests/integration/scripted_model.py` serves an OpenAI-shaped endpoint from a script
keyed on each agent's goal, so real worker processes can be driven through an exact
sequence: `test_scripted_escalation.py` runs a whole delegate-ask-escalate-answer-resume
cycle in nine seconds, deterministically.

The two gated tests answer different questions. `ANCALAGON_LIVE` asks whether a funded
model can do the work; `ANCALAGON_LOCAL_MODEL` asks whether a real provider accepts a
resumed transcript — one that ends with an answer to a question the agent asked — and
carries on from it. No fake can settle that, and a local model settles it for free.

## Design

`docs/architecture.md` follows a single run through every file it touches, in order --
start there if you are reading the code.

`docs/superpowers/specs/2026-08-02-ancalagon-agent-harness-design.md` is the design
rationale: what was chosen, what was deliberately cut, and why.
