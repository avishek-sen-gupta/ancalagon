# The after hooks a role declared for one tool, run in order until one refuses.
import dataclasses

import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.after import After
from ancalagon.tools.registry.tool_context import ToolContext


@dataclasses.dataclass(frozen=True)
class CompositeAfter(After):
    hooks: tuple[After, ...]

    def __call__(self, args: pydantic.BaseModel, ran: ToolResult, ctx: ToolContext, /) -> Reviewed:
        match self.hooks:
            case (first, *rest):
                return self._rest(first(args, ran, ctx), args, tuple(rest), ctx)
            case _:
                return Accepted(value=ran)

    def _rest(
        self,
        reviewed: Reviewed,
        args: pydantic.BaseModel,
        rest: tuple[After, ...],
        ctx: ToolContext,
    ) -> Reviewed:
        match reviewed:
            case Refused():
                return reviewed
            case Accepted(value=accepted):
                return self._onward(accepted, args, rest, ctx)

    def _onward(
        self,
        accepted: pydantic.BaseModel,
        args: pydantic.BaseModel,
        rest: tuple[After, ...],
        ctx: ToolContext,
    ) -> Reviewed:
        if not isinstance(accepted, ToolResult):
            got = type(accepted).__name__
            return Refused(reason=f"an after hook returned {got}, not ToolResult")
        return CompositeAfter(rest)(args, accepted, ctx)
