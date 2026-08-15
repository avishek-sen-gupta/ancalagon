# A tool with its argument type erased, so a registry can hold tools of differing shapes.
import collections.abc

import pydantic

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext


class BoundTool(pydantic.BaseModel, frozen=True):
    name: str
    cost: int
    declaration: ToolSchema
    invoke: collections.abc.Callable[[str, ToolContext], ToolResult]
