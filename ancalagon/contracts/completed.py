import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind

OutT = typing.TypeVar("OutT", bound=pydantic.BaseModel)


class Completed(pydantic.BaseModel, typing.Generic[OutT], frozen=True):
    kind: typing.Literal[OutcomeKind.COMPLETED] = OutcomeKind.COMPLETED
    value: OutT
    summary: str
    spent: Budget
