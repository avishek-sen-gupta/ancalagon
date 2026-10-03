# Everything about a tool that is knowable before it is bound to one agent.
import dataclasses

from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_schema import ToolSchema


@dataclasses.dataclass(frozen=True)
class ToolSpec:
    source: type[AnyTool]
    category: ToolCategory
    cost: int
    declaration: ToolSchema
