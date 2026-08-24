# The before hook a tool gets when its role declares none.
import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.tool_context import ToolContext


def unchecked_before(args: pydantic.BaseModel, ctx: ToolContext) -> Reviewed:
    return Accepted(value=args)
