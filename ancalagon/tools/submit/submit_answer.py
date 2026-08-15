# Ends a run with a typed answer; its parameter schema is the task's output class.
import json

import pydantic

from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class SubmitAnswer(Tool[pydantic.BaseModel]):
    name = "submit_answer"
    cost = 0

    def __init__(self, output_class: type[pydantic.BaseModel]):
        self.args_model = output_class
        fields = list(output_class.model_json_schema().get("properties", {}))
        example = json.dumps({f: "..." for f in fields})
        self.description = (
            "Submit your final answer. Call this exactly once, when you are done. "
            f"Its arguments are the answer itself: pass {', '.join(fields)} at the top "
            f"level, for example {example}. Do not wrap them in another object or "
            "pass them as a JSON string. This does not consume your tool-call budget."
        )

    def run(self, args: pydantic.BaseModel, ctx: ToolContext) -> ToolResult:
        payload = Submitted(answer=args)
        path = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=path)
