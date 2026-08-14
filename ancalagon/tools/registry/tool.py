# What every tool must offer, including the model its raw JSON arguments validate against.
import typing

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class Tool(typing.Protocol):
    name: str
    description: str
    cost: int
    args_model: type[pydantic.BaseModel]

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, self.args_model)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult: ...
