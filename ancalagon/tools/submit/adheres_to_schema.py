# Refuses an answer file that does not satisfy the JSON Schema the task's input named.
import json
import pathlib

import jsonschema

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.schema_guided import SchemaGuided
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _fault(error: jsonschema.ValidationError) -> str:
    where = "/" + "/".join(str(part) for part in error.absolute_path)
    return f"{where}: {error.message}"


def _validate(
    schema_path: pathlib.PurePath, answer_path: pathlib.PurePath, ctx: ToolContext
) -> tuple[str, ...]:
    validator: jsonschema.Draft202012Validator = jsonschema.Draft202012Validator(
        json.loads(ctx.workspace.read_text(schema_path))
    )
    return tuple(
        _fault(error)
        for error in validator.iter_errors(json.loads(ctx.workspace.read_text(answer_path)))
    )


def adheres_to_schema(args: AnswerFile, ctx: ToolContext) -> Reviewed:
    if not isinstance(ctx.input, SchemaGuided):
        return Refused(
            reason=f"this role's input contract does not name an output schema: {type(ctx.input).__name__}"
        )
    try:
        schema_path = ctx.workspace.resolve_read(ctx.input.output_schema)
        answer_path = ctx.workspace.resolve_write(args.path)
    except ScopeError as exc:
        return Refused(reason=str(exc))
    faults = _validate(schema_path, answer_path, ctx)
    return (
        Refused(reason=f"{answer_path} does not match {schema_path}:\n" + "\n".join(faults))
        if faults
        else Accepted(value=args)
    )
