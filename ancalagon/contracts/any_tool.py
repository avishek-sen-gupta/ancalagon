# A tool seen without its argument type, so one class can stand for any tool.
import typing

from ancalagon.contracts.tool_category import ToolCategory


class AnyTool(typing.Protocol):
    name: str
    description: str
    category: ToolCategory
    cost: int
