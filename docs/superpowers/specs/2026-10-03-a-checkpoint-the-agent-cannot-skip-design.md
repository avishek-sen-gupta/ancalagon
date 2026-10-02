# A checkpoint the agent cannot skip

## The problem

A long-lived agent's transcript grows without bound, and the only thing that shrinks what reaches
the model is demotion.

`for_wire` in `ancalagon/transcript/demote.py` estimates the transcript's size as
`sum(len(m.model_dump_json()) for m in messages) // 4` and, above `compact_above_tokens`, replaces
each tool-result body over `WORTH_DEMOTING` bytes with `[{byte_count} bytes at {path} — read_file
it if you need it]`. Nothing is removed. The message count never falls, every assistant turn's
reasoning stays verbatim forever, and a role with a generous budget — `turns = 200` in
`blackboard.toml` — accumulates two hundred turns of text that demotion cannot touch.

Demotion is exactly right about tool output. The bytes are already on disk under `tools/`, the
pointer is cheap, and `read_file` brings them back. It has nothing to say about a conclusion the
agent reached at turn 12 and still needs at turn 180, because that conclusion exists only in the
assistant text demotion leaves alone and nothing ever summarises. The part of the history that is
most expensive to rebuild is the part no mechanism touches.

Today the only answer is prose. `blackboard.toml` instructs three analysts, in six numbered steps,
to append their findings to a shared file and to read each other's before concluding. There is no
mechanism behind the instruction: a role that ignores it is not refused, and nothing notices. That
is the gap this closes. Not "agents should checkpoint their understanding" but "the harness
checkpoints it, and no role can be configured out of that."

## What this is not

**Not memory, and not retrieval.** A checkpoint is written at compaction and read back as part of
the next prompt. There is no index, no query, and no store an agent can ask a question of; nothing
crosses a run boundary. Checkpoints accumulating in `transcript.jsonl` would be the substrate for
that if it is ever wanted, and that is the only sense in which this anticipates it.

**Not a second evidence store.** `cite` already appends `Citation` records to `citations.jsonl` in
the task directory, where compaction cannot reach them. A checkpoint carries understanding and
never quotes. Asking the summariser for verbatim quotes would be worse than useless: it is an
out-of-band call reading a transcript it did not produce, `cite`'s quote-is-really-there check does
not apply to it, and a fabricated quote in the record is worse than no quote at all.

**Not a general lifecycle hook system.** One point is defined, `before_turn`, because one thing
needs it. There is no event bus, no ordering across points, and no subscriber that observes without
acting. `Sink` already exists for observation and is deliberately lossy — *"a run never waits on
its audience"* — which is precisely why it cannot carry this.

**Not a replacement for demotion.** `for_wire` stays and keeps its threshold. It is what happens
when a role declares no subscriber, and what happens when a declared subscriber's model call fails.
The two compose: a folded transcript is still demoted.

**Not an agent-callable tool.** A subscriber is never in a `Registry` and never reaches
`_declarations`, so it never appears in the model's tool list. An agent that could trigger its own
compaction could also decline to, which is the whole point. It is also not a `Tool`: `BoundTool.invoke`
is `Callable[[str, ToolContext], ToolResult]`, taking arguments as a JSON string because the model's
arguments arrive as text. Routing a message list through that would mean `model_dump_json` on the
transcript followed by `model_validate_json` straight back — the same defect written twice.

**Not a turn the agent pays for.** `Spend` is unchanged: compaction costs no turn and no tool call.
It does cost tokens, and those are metered against the agent that caused them.

## Design

### The cut point is the checkpoint's own coverage

The checkpoint states which messages it accounts for. There is no second value saying where to cut,
because the checkpoint already says: everything through `through_seq` is summarised, everything
after it is verbatim. One fact, stated once, by the thing that knows it.

```python
class OpenQuestion(pydantic.BaseModel, frozen=True):
    question: str = pydantic.Field(description="What is still not known.")
    reason: str = pydantic.Field(description="Why this attempt could not settle it.")


class Checkpoint(pydantic.BaseModel, frozen=True):
    from_seq: int
    through_seq: int
    established: tuple[str, ...]
    open_questions: tuple[OpenQuestion, ...]
    discarded: tuple[str, ...]


NO_CHECKPOINT = Checkpoint(
    from_seq=NO_WATERMARK, through_seq=NO_WATERMARK,
    established=(), open_questions=(), discarded=(),
)
```

`established`, `open_questions` and `discarded` are fixed slots rather than one prose field, because
the three are read for different reasons and a single string would let any of them swallow the
others. `discarded` is the one that is easiest to undervalue and hardest to rebuild: the evidence
that ruled a hypothesis out lived in the tool output compaction just dropped, so without this field
a compacted agent re-treads exactly the ground it already cleared.

There is no `next_step` and no list of paths that mattered. `next_step` invites the summariser to
invent an intention from a transcript it is only reading, and `access.jsonl` already records every
file an agent touched, involuntarily and without a model's help.

`NO_CHECKPOINT` reuses `NO_WATERMARK = -1` rather than inventing a second sentinel, and exists for
the same reason `NO_BUS`, `NO_SINK` and `NO_ANSWER_FILE` do.

### The checkpoint travels in the transcript

`Block` gains a fourth member and `BlockKind` a fourth value:

```python
class CheckpointBlock(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.CHECKPOINT] = BlockKind.CHECKPOINT
    checkpoint: Checkpoint


Block = Text | ToolUse | ToolResultBlock | CheckpointBlock
```

The wrapper is not ceremony. `Checkpoint` is also what the summarising call's schema asks a model to
fill, and a `kind` discriminator in that schema is a field the model has to be told to ignore.
Separating them keeps the model's contract clean and keeps block concerns out of the record.

Putting the checkpoint in `transcript.jsonl` rather than a sibling file is what preserves the
property `for_wire` already has: **the transcript is the record, the wire payload is a view.** The
record stays append-only and complete, the fold stays a pure function of it, and what the model saw
on any given turn can still be re-derived. It also means `Transcript.write` publishes the checkpoint
to the `Sink`, so `watch` shows a compaction as it happens, and `trace` and `viz` see it without
learning a second file.

`to_wire` in `ancalagon/llm/adapters/litellm_client.py` renders it to text. This is the serialisation
boundary and the only place a checkpoint becomes a string. One existing behaviour needs care: `to_wire`
returns `[]` when a message has neither text nor tool calls, so a message carrying only a
`CheckpointBlock` would silently vanish from the wire.

### The subscriber and what it is handed

```python
class Answer[T: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    value: T


class Checkpointing(typing.Protocol):
    def record(self, checkpoint: Checkpoint) -> None: ...


@dataclasses.dataclass(frozen=True)
class Compacting:
    messages: tuple[Message, ...]
    prompt_tokens: int
    above_tokens: int
    keep_recent: int
    llm: LLM
    checkpoints: Checkpointing


class Subscriber[T: pydantic.BaseModel](typing.Protocol):
    def __call__(self, ctx: Compacting, /) -> Answer[T]: ...
```

A subscriber reads the messages, decides whether the transcript has grown past `above_tokens`, makes
its own model call through `ctx.llm`, and records a `Checkpoint`. The record is the effect; the
return value is diagnostic.

`Compacting` is a frozen dataclass rather than a Pydantic model, for the same reason `ToolContext` is
a plain class: `LLM` and `Checkpointing` are protocols, and Pydantic cannot build a schema for one
without `arbitrary_types_allowed`, which would turn off validation for the fields that do need it.
`keep_recent` is in it because the subscriber, not the fold, chooses `through_seq` — it is the
threshold's other half, and a subscriber that could not see it would have to guess how much history
the fold was going to keep verbatim anyway.

The resolved subscribers are held on `Session` as `tuple[Subscriber[pydantic.BaseModel], ...]`, which
is legal precisely because of the covariance below.

`T` is pinned where the subscriber is wired — the one shipped here is
`Subscriber[Checkpoint]`. Because `T` appears only in return position it is covariant, so
`Answer[Checkpoint]` genuinely is an `Answer[BaseModel]` and a heterogeneous list of subscribers
needs no erasure. This is the mirror image of `Tool[ArgsT]`, which `docs/guidelines/refactoring.md`
records as unusable as a registry element type: `run` *consumes* its argument, making the parameter
contravariant, which is why `bind_tool` exists. Nothing equivalent is needed here.

**`Checkpointing` is a capability, not a file handle, and that is doing real work.** Handing a
subscriber the `Transcript` would let it write any message with any role, or `close()` the handle on
a live session. Handing it a path would not work at all: `Transcript` holds an open append handle, so
a second writer on `transcript.jsonl` can interleave, `seq`, `ts` and `agent` are the session's to
stamp and a subscriber cannot know them, and a hook-written line never reaches the `Sink`. One method
says exactly what a subscriber may do to the record, and Pyright stops anything else at authoring
time. `Session` supplies the implementation, wrapping its own `_record`.

**`ctx.llm` is metered.** `Session` passes a facade that calls `Meter.record(agent_id, usage)` on
every reply, so compaction's token cost lands in `model_calls` beside the agent's own calls and a
subscriber cannot avoid the accounting by construction. The agent's `Spend` is untouched — this is
harness overhead, not agent spend, and the distinction is visible because the two are recorded in
different places.

### The shipped subscriber

`ancalagon/compact/summarise.py` holds `summarise(ctx: Compacting) -> Answer[Checkpoint]`.

It is a module-level function, like every `before`/`after` hook and every `run` ref, so nothing has
to be constructed and everything it needs comes from `ctx`.

Below the threshold it records nothing and returns `Answer(value=NO_CHECKPOINT)`.

Above it, the summarising call reuses machinery that already exists rather than inventing a parser:
a one-element tool list from `schema_of("checkpoint", ..., Checkpoint)` with
`force_tool="checkpoint"`, exactly as `Session._loop` forces `submit_answer` on the final turn, then
`Checkpoint.model_validate_json` on the `ToolUse` arguments. Validated on arrival, at the boundary,
with no intermediate representation.

What it is given to summarise is **every prior checkpoint plus the messages since the last one** —
not the last checkpoint alone. Checkpoints are small, so the input stays bounded, and nothing is
paraphrased twice. Folding *n−1* into *n* would re-render every earlier conclusion at every
compaction and let a claim established at turn 5 drift or disappear by turn 200.

A failed or refused call is not fatal. The subscriber returns `Answer(value=NO_CHECKPOINT)`, records
nothing, and the turn proceeds on a demoted transcript. Degrading to today's behaviour is better
than failing a run over its own housekeeping.

### Where it is declared

`RawRole` and `Role` gain one field each, mirroring `before` and `after` exactly:

```python
# RawRole
session: dict[str, list[RawClassRef]] = {}

# Role
session: collections.abc.Mapping[str, tuple[FunctionRef, ...]] = {}
```

```toml
[roles.investigator.session]
before_turn = [{ module = "ancalagon.compact.summarise", name = "summarise" }]
```

A separate `[roles.*.session]` table rather than a key inside `before` is deliberate. `before` and
`after` are keyed by *tool name*; a lifecycle point sharing that namespace would mean a key that is
sometimes a tool and sometimes a phase, which is information encoded in a string and distinguished
only by convention. Here they are distinguished by position.

`resolve_subscriber` reuses `arity_fault` and `annotation_fault` from the existing hook resolution
and refuses, at startup, a function that does not take exactly one parameter annotated `Compacting`.
`accepts` itself is not reused: it exists to check a hook against the args model of the tool it is
wired to, and there is no tool here.

A role with no `session` table gets demotion and nothing else, which is current behaviour.

### The fold

`for_wire` gains the checkpoint case and keeps everything it already does:

- With no `CheckpointBlock` in the messages, it behaves exactly as it does today.
- With one, the wire payload is that checkpoint's message followed by every message after
  `through_seq`, then demoted as it is now.

The fold stays a pure function of the message list and the thresholds. It never looks at a
subscriber, never makes a call, and is tested by handing it a transcript that already contains a
checkpoint. This is why the fold can land before the producer does.

Message 0 is dropped with the rest. `Session._system` already re-sends `spec.goal` and
`input.model_dump_json()` as the `per_item` half of every system prompt, so the opening message is
redundant on the wire and has been since `SystemPrompt` split.

### Cutting without orphaning a tool result

`history.repair` handles one direction of this: a transcript ending in an assistant message with
unanswered `ToolUse` blocks gets synthetic `INTERRUPTED` results so the API accepts it. The mirror
case is unhandled and is the one a cut creates — a surviving `ToolResultBlock` whose `ToolUse` was
cut away, which providers reject outright.

The fold therefore does not cut at `through_seq` blindly. It advances past any leading message whose
blocks include a `ToolResultBlock` with no matching `ToolUse` among the messages being kept. Cutting
slightly later is always safe; cutting at an arbitrary index is not.

### Measured tokens, not an estimate

`for_wire`'s `sum(len(m.model_dump_json()) for m in messages) // 4` is a character-count
approximation of a token count the session already knows: `Session._complete` reads
`reply.usage.prompt_tokens` on every call and logs it. That measurement replaces the estimate, and
`Compacting.prompt_tokens` carries it.

This changes what `compact_above_tokens` means for every existing config, because the estimate and
the measurement do not agree. `ancalagon.example.toml` and `README.md` say so in the same commit.
On the first turn there is no prior reply and the value is 0, so nothing compacts before the model
has been called once — which is correct and needs no special case.

## Known debts

Two, both deliberate, recorded here so a later reader does not mistake them for oversights.

**`Answer[T].value` has no reader on day one.** `Session` ignores what a subscriber returns; the
recorded checkpoint is the whole effect. By the standard in `docs/guidelines/code-review.md` this is
machinery with no caller, the category `AgentSpec`, `outcome_adapter` and the `messages` table fell
into. It is accepted because the alternative is worse: a subscriber whose effect is a side effect and
whose signature returns nothing cannot later report a refusal, a count or a diagnostic without
changing every implementor, and `Any` and `object` are both banned outright, so a generic bounded by
`pydantic.BaseModel` is the only legal way to say "typed, pinned at wiring, not yet consumed". The
obvious first consumer is publishing it to the `Sink`.

**A total signature forces a meaningless no-op value.** Because the subscriber must return an
`Answer[T]` even when it decides not to compact, `NO_CHECKPOINT` exists to be returned and ignored.
This is the null-object pattern the codebase uses everywhere, so it reads correctly, but it is a
consequence of ignoring the return value rather than an independent design choice.

**One subscriber, one lifecycle point.** `before_turn` has exactly one implementor, which is the
shape `CLAUDE.md` names as gold plating. The honest answer to it is that the next subscriber is
already identifiable — `for_wire` itself is a pure `(messages, thresholds) -> messages` transform at
precisely this point, and making it a declared subscriber rather than a built-in would give the
mechanism two implementors and remove the hardcoded fallback. That is not done here, because it
changes the behaviour of every role that declares no subscriber, and it should be a change of its
own.

## Testing

1. **`tests/unit/test_demote.py` extends rather than gains a sibling**, per the rule in
   `docs/guidelines/testing-patterns.md`. One behaviour for the fold, asserting the whole of it on a
   hand-built transcript containing a `CheckpointBlock`: the returned sequence is exactly the
   checkpoint's message plus every message after `through_seq`, the cut has advanced past a leading
   orphaned `ToolResultBlock`, and a transcript with no checkpoint is demoted exactly as before.
   Concrete sequences, not lengths.
2. **`tests/unit/test_summarise.py`, one behaviour, with `FakeLLM`.** Scripted to return a forced
   `checkpoint` call, `summarise` records a `Checkpoint` equal to a stated value through a fake
   `Checkpointing` and returns it. The `Compacting` it is given carries a metered facade over that
   `FakeLLM`, so the test also asserts the call's usage reached the injected `Meter`. Below the
   threshold it
   records nothing and returns `NO_CHECKPOINT`. A `FakeLLM` scripted to fail leaves the record
   untouched and returns `NO_CHECKPOINT`. No `unittest.mock`.
3. **`tests/unit/test_config_load.py` extends** for the new table: a `[roles.*.session]` with
   `before_turn` resolves, and a function with the wrong arity or a first parameter not annotated
   `Compacting` is refused at load with a message naming the function.
4. **`tests/integration`**: a role declaring the subscriber, a `compact_above_tokens` low enough to
   fire mid-run, and a `FakeLLM`-free run that completes, writes an outcome, and leaves a
   `transcript.jsonl` containing at least one `CheckpointBlock` whose `through_seq` precedes the
   messages that follow it. The verification step runs `tests/integration` whole — forty seconds, and
   two plans in a row let a regression through by narrowing it to the one test they were about.
5. **Mutation-check every new test before trusting it.** Break the fold so it cuts at `through_seq`
   without skipping an orphaned result; break `summarise` so it ignores the threshold; break the
   metered facade so usage is dropped. A test written after the code is a hypothesis until it has
   failed once.

## Commits

Four, in this order.

1. **Measured tokens replace the estimate.** `for_wire` takes the count, `Session` passes
   `reply.usage.prompt_tokens`, the character approximation goes. No new capability, one behaviour
   change, and the one commit where a threshold shifting under existing configs is the only thing a
   reviewer has to think about. `ancalagon.example.toml` and `README.md` change here.
2. **`Checkpoint`, `CheckpointBlock`, `BlockKind.CHECKPOINT`, `to_wire` rendering, and the fold.**
   Still no producer. The fold is fully tested against hand-built transcripts, which is what makes
   this separately reviewable: a bug in the fold cannot be confused with a bug in the summariser
   when the summariser does not exist yet.
3. **`Answer[T]`, `Checkpointing`, `Compacting`, `Subscriber`, `resolve_subscriber`, the `session`
   table, and the metered facade.** The mechanism and its wiring, with the config test, which
   resolves a subscriber defined in the test module — no subscriber ships in `ancalagon` yet, and
   nothing calls one, so the only behaviour on offer is that a well-formed `session` table loads and a
   malformed one is refused. `ancalagon.example.toml` documents the table here.
4. **`summarise`, wired into `ancalagon.toml` and `blackboard.toml`.** The producer, its unit
   behaviour, and the integration test. `README.md` and `docs/architecture.md` gain the mechanism
   here: what a run leaves behind now includes checkpoints in the transcript, and `blackboard.toml`'s
   six prose steps lose the two that the harness now guarantees.

Commit 1 lands alone. If it arrives with commit 2, a reviewer cannot tell a threshold change from a
fold bug, which is the whole reason that seam is worth cutting first.
