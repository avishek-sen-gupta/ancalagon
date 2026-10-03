# Everything about a tool that is knowable before it is bound to one agent.
import pydantic

from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_schema import ToolSchema


class ToolSpec(pydantic.BaseModel, frozen=True):
    category: ToolCategory
    cost: int
    declaration: ToolSchema
