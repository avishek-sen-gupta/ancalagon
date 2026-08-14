# Ends a run with a typed answer; its parameter schema is the task's output class.
import json

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.unanswered import Unanswered
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class SubmitAnswer:
    name = "submit_answer"
    cost = 0

    def __init__(self, output_class: type[pydantic.BaseModel]):
        self.output_class = output_class
        self.answer: pydantic.BaseModel = Unanswered()
        schema = output_class.model_json_schema()
        fields = list(schema.get("properties", {}))
        example = json.dumps({f: "..." for f in fields})
        self.description = (
            "Submit your final answer. Call this exactly once, when you are done. "
            f"Its arguments are the answer itself: pass {', '.join(fields)} at the top "
            f"level, for example {example}. Do not wrap them in another object or "
            "pass them as a JSON string. This does not consume your tool-call budget."
        )

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            parameters_json=json.dumps(self.output_class.model_json_schema()),
        )

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        try:
            self.answer = self.output_class.model_validate_json(arguments)
        except pydantic.ValidationError as exc:
            return ctx.failure(self.name, f"answer did not match the schema: {exc}")
        return ctx.result(self.name, "answer accepted")
