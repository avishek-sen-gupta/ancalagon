# A typed answer file

## The problem

`submit_answer_as_file` checks only that the file it is given exists. What the file holds is
checked, if at all, by an opt-in hook, `adheres_to_schema`, against a JSON Schema whose path the
task's input names through `SchemaGuided`. A role that wires no hook submits an unchecked file,
and a role that wires it validates against a contract that is never a Python value.

Every other answer in the harness is a Pydantic instance by the time it leaves the model.
`submit_answer` takes its class at construction and its arguments are validated into it. The file
route should work the same way: the tool is constructed with the class the file must hold, and
refuses a file that does not validate into it.

## What this is not

**Not a change to what a parent receives.** `role.answer` stays `AnswerFile` — status, summary,
path — and `collect_task` validates a child's outcome against it as it does now. The content
class governs the file; the parent still pays three fields, not the record.

**Not optional.** A role that names `submit_answer_as_file` must name the class its file holds.
There is no untyped file route.

**Not per task.** The class is fixed by the role at startup, where it can be checked. A parent
that needs a different shape delegates to a different role.

## Design

### The role names the content class

`Role` gains `answer_file: ClassRef`, defaulting to `NO_ANSWER_FILE`, a null object in the manner
of `NO_RUN`. The config reads it as `answer_file = { module = ..., name = ... }`.

```toml
[roles.record_analyst]
answer = { module = "ancalagon.contracts.answer_file", name = "AnswerFile" }
answer_file = { module = "example.contracts.record", name = "Record" }
tools = ["read_file", "write_file", "edit_json", "submit_answer_as_file"]
```

### The tool validates on submission

`SubmitAnswerAsFile(content_class)` resolves the path through the workspace as now, reads the
file, and calls `content_class.model_validate_json` on its text. Invalid JSON and a structural
mismatch both surface as `pydantic.ValidationError`, so there is one refusal path: a tool failure
that lists every fault, after which the run continues and the model may fix the file and submit
again. A missing file remains a failure of its own. On success the tool submits `AnswerFile`
exactly as it does today.

The validated instance is not carried upward. The file is the answer; the parent receives the
pointer and opens the file if it wants the record.

The model must know the shape before it writes the file, not only after a refusal. The tool's
description includes `content_class.model_json_schema()`, rendered to text there — the prompt is
the wire — as `submit_answer`'s description lists its fields.

### Startup checks the class

`check_contracts` gains three faults:

- `answer_file` names a class that cannot be loaded.
- A role names `submit_answer_as_file` and leaves `answer_file` at `NO_ANSWER_FILE`.
- A role sets `answer_file` and does not name `submit_answer_as_file` — a contract that is never
  enforced reads as one that is, which is the same reasoning that rejects a hook on an unnamed
  tool.

The existing rule that such a role's `answer` is `AnswerFile` stays.

`session_for` and `check_contracts` resolve `answer_file` beside `answer` and pass the class to
`build_registry`, which constructs `SubmitAnswerAsFile` with it. `NO_ANSWER_FILE` resolves to a
real, fieldless class so the tool can always be constructed; the registry withholds it from any
role that does not name it.

### The JSON Schema route is removed

`SchemaGuided`, `adheres_to_schema`, their tests and the `jsonschema` dependency are deleted. The
architecture document's paragraph justifying a parsed JSON value that never becomes a model goes
with them: after this change there is no such place.

### The research example writes JSON

Both roles in `research.toml` submit markdown today. They move to JSON files validated against
two models in `ancalagon/research/`, each stating what the role's prompt already demands:

- `Findings`, for a researcher: entries, each with what the thing does, how its enforcement
  works, what it requires, the URL it was read on, and whether it is verified.
- `Report`, for the root: where the approaches differ, the cited claims, and what could not be
  determined and why.

The prompts change from writing `.md` to building `.json` with `write_file` and `edit_json`.

## Testing

- `tests/unit/test_answer_file.py` — one behaviour test of the tool: a valid file submits
  `AnswerFile`; an invalid file fails naming every fault and the run continues; a missing file
  fails.
- `tests/unit/test_config_load.py` — one startup test covering an unloadable, missing and stray
  `answer_file`.
- `tests/integration/test_answer_as_file.py` — the schema hook is replaced by a content class.

## Commits

1. The typed tool, the `answer_file` field, the startup checks, the research migration, README,
   `docs/architecture.md` and `ancalagon.example.toml`. The research migration rides in this
   commit because `research.toml` would fail startup without it.
2. Remove `SchemaGuided`, `adheres_to_schema` and `jsonschema`.
