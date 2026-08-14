# Ends a run with a question; there is no channel to ask a live parent by design.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.need_input.need_input_args import NeedInputArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class NeedInput(Tool):
    name = "need_input"
    description = (
        "Stop and hand a question back to whoever launched this task. "
        "Use when you cannot proceed without information you have no way to obtain. This does not consume your tool-call budget."
    )
    cost = 0

    def __init__(self) -> None:
        self.question = ""

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, NeedInputArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = NeedInputArgs.model_validate_json(arguments)
        self.question = args.question
        return ctx.result(self.name, f"question recorded: {args.question}")
