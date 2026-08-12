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
   │ enqueue                      │ outcome.json
   ▼                              │
 bus.db ◀──claim──── supervisor ──┴──spawn──▶ worker ──▶ Session ──▶ llm ──▶ provider
                                                            │
                                                            └──▶ tools ──▶ files
```

## The trace

### 1. Starting a run — `ancalagon/cli.py`

`main(config_path, goal)`:

1. `config/load.py` reads the TOML. Relative roots resolve against the **config file**, not
   the process cwd, so a worker started elsewhere sees the same paths.
2. `run_dir_of` uses `[run] run_dir` when set and allocates `<write_root>/runs/r_NNNN` when not.
   A named directory is created if absent and reused if present, which is what makes a second
   invocation continue rather than start over; an allocated one must not already exist.
3. Writes two files into `<run_dir>/tasks/root/`: `contracts.py` — `[run] contract`'s module when
   named, otherwise `contracts/free_text_module.py` — and `spec.json` naming the class it must
   answer in. The goal comes from `[run] goal_file` or `--goal`; exactly one. A missing or empty
   file, or a `contract` naming a class its module does not define, exits 2 before any spawn.
4. `bus/bus.py` opens `bus.db` and enqueues the task with `parent_agent=0`. Enqueuing creates
   the task if new, adds an agent, and appends a `queued` event; a task retried later reuses
   the task row and adds another agent.
5. Constructs the `Supervisor` and calls `run_until_idle()`, then `shutdown()` in a
   `finally`.
6. Prints `tasks/root/outcome.json`. Any outcome from a previous attempt is deleted before
   enqueuing, so a run that dies without writing one exits 1 instead of reporting the old one.

The CLI never spawns anything and never speaks to a model.

Opening a bus migrates it to the latest version — on every open, not only the first — so a
database written by an older build is upgraded in place. A migration that has shipped is
therefore never edited: databases already at that version skip it, so the edit reaches new
runs only and leaves older ones missing the change. Add a numbered migration instead.

### 2. Supervising — `ancalagon/supervisor/supervisor.py`

`run_until_idle()` loops on `tick()`:

- `_start_queued` claims **one agent at a time** — `bus.claim(limit=1)`, which appends
  `claimed` — and spawns it before claiming the next. Claiming a batch first would strand
  siblings if one spawn failed. After spawning it appends `running` with the pid; a failed
  spawn appends `crashed` and reports to the parent.
- `_reap` polls each live process and appends what it sees: `exited` on a zero exit,
  `crashed` otherwise. A process past `agent_timeout_s` is killed, given a `TimedOut`
  outcome file, and recorded `timed_out`.
- The loop exits when nothing is live and nothing is queued. Agents the database thinks are
  `claimed` or `running` but which this supervisor does not own are orphans from a previous
  supervisor, and are recorded `abandoned`.

Nothing is ever updated: every status is a new row, so an agent's whole history survives.
The worker appends its own account too — `completed`, `needs_input`, `exhausted` or
`failed` — which is why the log finally agrees with `outcome.json`.

It never retries. A crash is reported; the parent decides.

`subprocess_spawner.py` is the only module that constructs a process. `process.py`,
`spawner.py` and `clock.py` are protocols so the supervisor can be tested without launching
interpreters or waiting on real time.

### 3. One attempt — `ancalagon/worker.py`

Invoked as `python -m ancalagon.worker --run-dir … --dir … --agent-id … --config …`.

`main` opens the transcript **first**, so even a failure mid-setup leaves a record, then:

1. Reads `spec.json` as `TaskSpec` — the scalars only. The `input` is pulled out separately
   as text by `contracts/input_json.py`, because the worker cannot know its class.
2. `contracts/resolve.py` imports the task's `contracts.py` and returns the output class,
   refusing any path outside the task directory.
3. If a `transcript.jsonl` already exists, `transcript/history.py` loads and **repairs** it:
   a transcript ending in an unanswered tool call is rejected by the API, so interrupted
   calls get synthetic error results. This is the whole of resumption — there is no
   "resume mode".
4. Builds `SubmitAnswer(output_class)` and `NeedInput()` **once**, and passes the same
   instances to both `build_registry` and the `Session`. Different instances would mean the
   model fills one form while the session reads another.
5. Runs the session, appends the agent's own outcome to the event log, writes
   `outcome.json`, and returns 0.

Any exception writes a `Failed` outcome and returns 1, so a task is never left
uncollectable.

`build_registry` is the only place tool availability is decided: `[tools] enabled` filters
the list, and `delegate` is withheld once `bus/depth_of.py` reports the task is at
`max_depth`.

### 4. The loop — `ancalagon/session.py`

`run()` is the centre of the system:

```
while True:
    budget empty? ─────────────────▶ _final_turn() ──▶ Exhausted | Failed
    spend a turn
    reply = llm.complete(_system(), messages, schemas)
    record it
    did it call tools?
        yes ─▶ _run_tools()
               need_input.question set? ──▶ NeedsInput
               submit.answer_json set?   ──▶ Completed
               loop
        no  ─▶ parse the text as the output class
               valid?   ──▶ Completed
               invalid? ──▶ tell it so, loop
```

Four things worth knowing:

- **The run ends in exactly three places**, all visible above. `submit` and `need_input` are
  constructor arguments precisely so this is readable rather than hidden behind registry
  lookups.
- **`_run_tools` refuses calls past the budget** rather than letting it go negative, and
  returns the refusal to the model as an error result.
- **A tool that raises is caught** and becomes an error result. Tool failure is a value the
  agent reads and corrects; it never breaks the loop.
- **`_final_turn` offers only `submit_answer`**, and injects a synthetic assistant turn
  first if the last message was a user turn — providers reject two consecutive user turns.
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

`registry/registry.py` maps the model's tool name to an object. Each tool then:

1. Validates its own arguments from the raw JSON string into a private Pydantic model. This
   is why no `Any` appears in the tool layer — the registry never sees a parsed structure.
2. Resolves paths through `workspace/workspace.py`, which `resolve()`s first and then checks
   containment, so `..` and symlinks are handled by the same check.
3. Writes its full output to a file under the task's `tools/` directory and returns a
   `ToolResult` carrying a capped summary and that path.

The session puts the summary and the path into the tool result the model sees. Large output
never enters the context; the model reads it with `read_file` if it wants to.

`submit/submit_answer.py` and `need_input/need_input.py` are the two tools the session
watches. `delegate/` writes a child's `spec.json` and enqueues it — it does not spawn;
the supervisor does.

### 6. Talking to a provider — `ancalagon/llm/`

`llm.py` is the only seam between the loop and any provider. `fake_llm.py` implements it
with scripted replies, which is what makes the entire loop testable offline.

`adapters/litellm_client.py` carries `num_retries` and `timeout` from config, so a transient 429 or 5xx is retried rather than killing the task. It translates in both directions: our `Message` objects become
`wire_message.py` models dumped to OpenAI-shaped dicts, and the response becomes `Text` and
`ToolUse` blocks. The `adapters/` directory is quarantined in `pyrightconfig.json` — it is
the only place third-party type gaps are tolerated.

## What a run leaves behind

```
ws/runs/r_0001/
    bus.db                        tasks, agents, every event about them, every model call
    tasks/root/
        spec.json                 what was asked
        contracts.py              the output contract
        transcript.jsonl          every message, one per line, tagged by agent id
        outcome.json              the result
        stderr-1.log              the worker's stderr
        tools/0000-read_file.txt  every tool's full output
    tasks/<child>/                same shape, one per delegated task
```

Because the transcript is flushed per message, a run is watchable while it happens:

```bash
tail -f ws/runs/r_0001/tasks/root/transcript.jsonl
```

Everything is inspectable without ancalagon:

```bash
sqlite3 ws/runs/r_0001/bus.db \
  "select agent, status, source, exit_code, summary from agent_events order by id"
sqlite3 ws/runs/r_0001/bus.db \
  "select agent, count(*), sum(prompt_tokens), sum(cache_read_tokens)
   from model_calls group by agent"
rg '"agent": 1' ws/runs/r_0001/tasks/root/transcript.jsonl
```

There is no `ancalagon usage` verb. `run` is the only command; the schema is the query
surface, and `Bus.calls` and `Bus.tokens_by_agent` are the same two queries for callers
already holding a bus.

## Where to start reading

| Question | File |
|---|---|
| How does an agent turn work? | `session.py` |
| What can an agent do? | `worker.py`, `build_registry` |
| How does work get scheduled? | `supervisor/supervisor.py` |
| What crosses a boundary? | `contracts/` |
| How is a provider called? | `llm/adapters/litellm_client.py` |
| What stops an agent escaping? | `workspace/workspace.py` |
