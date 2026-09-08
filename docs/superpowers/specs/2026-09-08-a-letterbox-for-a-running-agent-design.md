# A letterbox for a running agent

## The problem

A run can go wrong in a way a human watching it can name in one sentence, and today there is
nothing to do with that sentence. The two existing human channels both require the agent to have
stopped: `answer` demands a prior `needs_input` event, and everything else waits for an outcome.
So an operator watching an agent drift has one lever, which is to kill the run and lose whatever
real work it had already done.

The observed case was an agent that spent a whole budget re-encoding the same tool arguments
because its own history had taught it a wrong shape. A human could see the defect from the log
after two attempts. There was no way to say so.

## What this is not

**Not an interrupt.** A model call in flight cannot be interrupted, and a turn is the unit the
loop is built from. A note is read at the top of a turn. "Mid-turn" is impossible; "before the
next turn" is what is on offer.

**Not an undo.** A note lands at the end of the context, which is the strongest position an
instruction can occupy, but it does not remove what is already there. An agent that has
accumulated many turns of a bad pattern is not reliably reformed by one line of correction, and
an agent that has abandoned its task is not reformed at all. The value is in catching drift
early, while the run is still worth saving.

**Not configuration.** A note carries text. It does not grant budget, change tools, or set
policy.

## Why not the bus

Two bus-shaped designs were considered and rejected.

**New `note` and `noted` statuses on `agent_events`, with a `human` source.** Two independent
problems. SQLite cannot `ALTER` a `CHECK` constraint, so widening the status vocabulary means
rebuilding `agent_events` and copying it. Worse, `agent_events` is where the scheduler reads an
agent's *latest* status — `latest_event`, `active_for` and the queued-state guard all consult it
— so an appended `note` event would become the agent's current state and would have to be
excluded from every one of those reads. That is a large blast radius to buy a text injection.

**A `notes` table in migration `003`.** Sound, and it buys a transactional claim so a note
cannot be delivered twice. It costs a table nothing else in the system reads, and the
concurrency it protects against is a human typing at a terminal, who does not race themselves.

The deciding observation is that human text does not go through the bus today. `answer_task`
appends a USER `Message` to the task's `transcript.jsonl` and enqueues a fresh attempt; the bus
carries only the enqueue. A note is the same act minus the enqueue, so it belongs in the same
place.

## Design

### Notes on disk

A note is a file: `<task_dir>/notes/<stamp>.txt`, whose content is the note verbatim. The stamp
comes from the clock, so a lexical sort of the directory is chronological — the same convention
the run directories already use.

Plain text, not JSON with a model around it. Prose bound for a prompt is text under the boundary
rules; a model with a single `text` field would state no contract that the file does not.

One file per note rather than lines appended to a shared `notes.jsonl`. Draining a shared file
means reading it and then removing it, and a note appended between those two steps is lost with
no trace. With a file per note, a note written during a drain is simply not in that drain's
listing and is picked up on the next turn.

### The seam

`Letterbox` is a protocol of two methods, mirroring `Children` — the contract the session
already uses for external state it consults every turn:

```python
class Letterbox(typing.Protocol):
    def unread(self) -> tuple[str, ...]: ...

    def mark(self, delivered: int) -> None: ...
```

`FileLetterbox(fs, task_dir)` lists `notes/*.txt`, sorts by name, and returns the contents.
`mark(n)` removes the first `n` of that same ordering. `NO_LETTERBOX` returns `()` and ignores
`mark`, so a session without a letterbox is a choice rather than a branch.

`mark` takes a count rather than clearing everything, because a note that arrives between
`unread` and `mark` must not be removed without having been delivered.

### Folding a note into the turn

At the top of the loop in `run()`, before the budget is read:

```python
notes = self.letterbox.unread()
for note in notes:
    self._record(MessageRole.USER, [Text(text=f"{NOTE_PREFIX}{note}")])
self.letterbox.mark(len(notes))
```

Folding costs no turn: no model call is made, and the budget is untouched.

`_record` appends to the session's messages and writes the transcript in one act, so a delivered
note is part of the history every later agent on that task replays. That is what makes a note
survive a restart of the run.

Recording happens before marking, deliberately. A crash between the two re-delivers the note on
the next attempt; the reverse order would lose it silently. A repeated human instruction is a
far cheaper failure than a vanished one.

`NOTE_PREFIX` exists because a bare sentence appearing as a USER message is indistinguishable
from the task. An answer needs no such marking, since it arrives in reply to a question the agent
asked.

### The command

```
ancalagon note --run-dir R --agent N --text "..."
```

`note_task` opens the bus, resolves the agent to its task through `task_of`, and writes the file
into that task's `notes/` directory — the same resolution `answer_task` performs. Empty text is
rejected at the command, where the operator can see the complaint, not inside the session.

The command reports what actually happens: the note is addressed to a *task*, and is delivered
by whichever agent next runs it.

## Semantics and limits

**A note is task-scoped, not agent-scoped.** Addressing is by agent number because that is what
the log prints, but the note is left for the task. If the agent named has already exited, the
next attempt on that task delivers it. This is what makes notes survive restarts, and it is the
honest description of the guarantee.

**A note to an idling agent waits.** An agent idling on its children is not running a loop, so
nothing drains its letterbox until something else wakes it. Waking it would mean teaching the
scheduler that a note is news, which is a scheduling change rather than a text injection, and is
out of scope here.

**Delivery is at most once per turn boundary.** A note written while a model call is in flight
arrives at the start of the following turn.

## Implementation units

Four commits, each independently reviewable.

1. **The letterbox.** `Letterbox` protocol, `NO_LETTERBOX`, `FileLetterbox`. Unit tests for
   ordering, for `mark` consuming a prefix of that ordering, and for a note written between
   `unread` and `mark` surviving.
2. **Session folds notes.** The `letterbox` constructor parameter defaulting to `NO_LETTERBOX`,
   and the fold at the top of `run()`. A unit test with a scripted letterbox asserting the note
   reaches the model as a USER message, appears in the transcript, and costs no turn.
3. **The command.** `note_task`, `note_command`, the parser entry, and the README and
   architecture updates. Unit tests for the file landing in the right task directory and for
   empty text being refused.
4. **Wiring.** One line in the worker, `letterbox=FileLetterbox(fs, task_dir)`, plus an
   integration test that leaves a note before the run starts and asserts a real worker
   subprocess folds it into its first turn.

## Testing

Unit tests use `tmp_path` and the real file system, as the transcript tests do. The session test
uses a scripted fake in the shape of `ScriptedChildren`, not a mock.

The integration test proves the wiring end to end by pre-seeding the note, which needs no timing:
a note present before the first turn exercises the same drain a mid-run note would.
