# What every tool must offer. Each validates its own arguments from raw JSON text.
import typing

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class Tool(typing.Protocol):
    name: str
    description: str
    cost: int

    def schema(self) -> ToolSchema: ...

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult: ...
