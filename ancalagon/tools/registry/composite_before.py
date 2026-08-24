# The before hooks a role declared for one tool, run in order until one refuses.
import dataclasses

import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.tools.registry.before import Before
from ancalagon.tools.registry.tool_context import ToolContext


@dataclasses.dataclass(frozen=True)
class CompositeBefore(Before):
    hooks: tuple[Before, ...]

    def __call__(self, args: pydantic.BaseModel, ctx: ToolContext, /) -> Reviewed:
        match self.hooks:
            case (first, *rest):
                return self._rest(first(args, ctx), type(args), tuple(rest), ctx)
            case _:
                return Accepted(value=args)

    def _rest(
        self,
        reviewed: Reviewed,
        wanted: type[pydantic.BaseModel],
        rest: tuple[Before, ...],
        ctx: ToolContext,
    ) -> Reviewed:
        match reviewed:
            case Refused():
                return reviewed
            case Accepted(value=accepted):
                return self._onward(accepted, wanted, rest, ctx)

    def _onward(
        self,
        accepted: pydantic.BaseModel,
        wanted: type[pydantic.BaseModel],
        rest: tuple[Before, ...],
        ctx: ToolContext,
    ) -> Reviewed:
        if not isinstance(accepted, wanted):
            got = type(accepted).__name__
            return Refused(reason=f"a before hook returned {got}, not {wanted.__name__}")
        return CompositeBefore(rest)(accepted, ctx)
