# What every tool must offer. Its arguments arrive parsed; bind_tool does the parsing.
import typing

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool_context import ToolContext

ArgsT = typing.TypeVar("ArgsT", bound=pydantic.BaseModel)


class Tool(typing.Protocol[ArgsT]):
    name: str
    description: str
    cost: int
    args_model: type[ArgsT]

    def run(self, args: ArgsT, ctx: ToolContext) -> ToolResult: ...
