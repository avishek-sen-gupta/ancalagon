import json

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class SubmitAnswer:
    name = "submit_answer"
    description = "Submit your final answer. Call this exactly once, when you are done."

    def __init__(self, output_class: type[pydantic.BaseModel]):
        self.output_class = output_class
        self.answer_json = ""

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters_json=json.dumps(self.output_class.model_json_schema()),
        )

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        try:
            self.output_class.model_validate_json(arguments)
        except pydantic.ValidationError as exc:
            return ctx.failure(self.name, f"answer did not match the schema: {exc}")
        self.answer_json = arguments
        return ctx.result(self.name, "answer accepted")
