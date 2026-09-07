# Ends a run with a pointer to the answer on disk, for a contract too large to emit in one reply.
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class SubmitAnswerAsFile(Tool[AnswerFile]):
    name = "submit_answer_as_file"
    description = (
        "Submit your final answer as a file you have already written with write_file and "
        "edit_json. Call this exactly once, when you are done. Give the path to that file, "
        "whether the answer is complete or partial, and one sentence describing it. This "
        "does not consume your tool-call budget."
    )
    cost = 0
    args_model = AnswerFile

    def run(self, args: AnswerFile, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not ctx.workspace.is_file(path):
            return ctx.failure(self.name, f"no answer file at {path}")
        payload = Submitted(answer=args)
        written = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=written)
