# What a hook that runs after a tool must offer.
import typing

import pydantic

from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool_context import ToolContext


@typing.runtime_checkable
class After(typing.Protocol):
    def __call__(
        self, args: pydantic.BaseModel, ran: ToolResult, ctx: ToolContext, /
    ) -> Reviewed: ...
