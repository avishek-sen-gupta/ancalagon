# The after hook a tool gets when its role declares none.
import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool_context import ToolContext


def unchecked_after(args: pydantic.BaseModel, ran: ToolResult, ctx: ToolContext) -> Reviewed:
    return Accepted(value=ran)
