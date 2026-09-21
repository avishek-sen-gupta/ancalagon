# Ends a run with a pointer to the answer on disk, once the file validates into the role's class.
import json
import pathlib

import pydantic
import pydantic_core

from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


def _fault(error: pydantic_core.ErrorDetails) -> str:
    return "/" + "/".join(str(part) for part in error["loc"]) + f": {error['msg']}"


def _mismatch(content_class: type[pydantic.BaseModel], path: pathlib.PurePath, text: str) -> str:
    try:
        content_class.model_validate_json(text)
        return ""
    except pydantic.ValidationError as error:
        faults = "\n".join(_fault(detail) for detail in error.errors())
        return f"{path} does not match {content_class.__name__}:\n{faults}"


def _content_fault(
    content_class: type[pydantic.BaseModel], ctx: ToolContext, path: pathlib.PurePath
) -> str:
    if not ctx.workspace.is_file(path):
        return f"no answer file at {path}"
    return _mismatch(content_class, path, ctx.workspace.read_text(path))


class SubmitAnswerAsFile(Tool[AnswerFile]):
    name = "submit_answer_as_file"
    cost = 0
    args_model = AnswerFile

    def __init__(self, content_class: type[pydantic.BaseModel]):
        self.content_class = content_class
        self.description = (
            "Submit your final answer as a file you have already written with write_file and "
            "edit_json. Call this exactly once, when you are done. Give the path to that file, "
            "whether the answer is complete or partial, and one sentence describing it. The "
            "file must be JSON matching this schema, and is refused with every fault listed if "
            f"it does not: {json.dumps(content_class.model_json_schema())}. This does not "
            "consume your tool-call budget."
        )

    def run(self, args: AnswerFile, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        fault = _content_fault(self.content_class, ctx, path)
        if fault:
            return ctx.failure(self.name, fault)
        payload = Submitted(answer=args)
        written = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=written)
