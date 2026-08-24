# What a hook that runs before a tool must offer.
import typing

import pydantic

from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.tool_context import ToolContext


@typing.runtime_checkable
class Before(typing.Protocol):
    def __call__(self, args: pydantic.BaseModel, ctx: ToolContext, /) -> Reviewed: ...
