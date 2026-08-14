# A tool with its argument type erased, so a registry can hold tools of differing shapes.
import collections.abc

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class BoundTool:
    def __init__(
        self,
        name: str,
        description: str,
        cost: int,
        args_model: type[pydantic.BaseModel],
        invoke: collections.abc.Callable[[str, ToolContext], ToolResult],
    ):
        self.name = name
        self.description = description
        self.cost = cost
        self.args_model = args_model
        self.invoke = invoke

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, self.args_model)
