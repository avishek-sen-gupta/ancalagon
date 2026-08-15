## Refactoring Principles

### Replacing a primitive with a type

When a value stops being a `str` and becomes a model or a class, map the blast radius before
starting and find every construction site structurally with `ast-grep` rather than by reading.

- **Push the wrapping to the origin.** Parse where the value arrives, not at every consumer.
  `bind_tool` turns a tool call's JSON into the tool's args model in one place; before that,
  twenty-one tools each called `model_validate_json` on the same string.
- **No coercion validators.** Never add a `field_validator` or `__post_init__` that quietly
  converts a string into the type. It hides the call sites that should have been updated. If
  Pydantic rejects a value, the caller is wrong — fix the caller.
- **No defensive `isinstance` checks.** `x if isinstance(x, T) else T(x)` means the callers
  disagree. Fix the callers.
- **Carry the class, not its rendering.** `ToolSchema` held `parameters_json: str`, produced by
  dumping a model's schema and parsed straight back by the adapter. Holding
  `parameters: type[BaseModel]` deleted the round trip and moved the serialisation to the wire,
  where it belongs.
- **Keep what parsing produced.** `submit_answer` validated its arguments, discarded the
  instance, and stored the raw text, which the session then parsed again. If you have called
  `model_validate_json`, you already have the value.
- **A constraint belongs on the field.** `schema_of` builds a tool's schema from its args model,
  so a `pattern`, a `default` and a `description` are shown to the model *before* it calls. A
  hand-rolled check inside `run` can only report afterwards. The two are not equivalent:
  `delegate`'s answer contract was checked in `run`, the model saw a bare string, and it guessed
  wrong six times in one turn.
- **Name the field after what it holds.** That same field was called `output`, which invited the
  model to answer "what kind of output?" — it replied `"text"`. It holds a class reference, and
  is now `answer_schema`.
- **A type parameter can be scoped but not stored.** `Tool[ArgsT]` cannot be an element type of a
  heterogeneous registry: `run` consumes its argument, so the parameter is contravariant and
  `Tool[GrepArgs]` is not a `Tool[BaseModel]`. Enumerating a union fails too when one member is
  generated at runtime. A generic *function* keeps the parameter in scope and hands back an
  erased value — that is what `bind_tool` is for.
- **Grep for the old shape before committing.** A rename that Pyright accepts can still leave
  string literals behind: dict keys, JSON fixtures, `getattr` names, `[tools] enabled` entries.
  Search for the old name as text, not just as a symbol.
- **Serialise only at the boundary.** `model_dump_json` belongs where text is genuinely wanted —
  a file, the wire, a prompt, a summary. Never in the middle of a pipeline to feed something
  that will parse it again.

### Working across the codebase

- **One logical change per commit, even when mechanical.** Declaring `Tool` inheritance, adding
  `args_model`, and typing `run` were three commits touching the same twenty-one files. Each was
  separately reviewable and separately revertible.
- **Prove the change catches what it claims.** After adding a guard or a type, break the thing it
  protects and confirm the failure lands where you said it would — and where the error message
  points. An error reported against a distant list is worse than one reported at the class.
- **Mutation-check a new test before trusting it.** Break the code it covers in the two most
  obvious ways and confirm the test fails. A test written after the code is a hypothesis until
  it has failed at least once.
