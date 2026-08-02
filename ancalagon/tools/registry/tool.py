import typing

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class Tool(typing.Protocol):
    name: str
    description: str

    def schema(self) -> ToolSchema: ...

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult: ...
