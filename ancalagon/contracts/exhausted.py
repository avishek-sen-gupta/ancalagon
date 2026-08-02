import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import OutT
from ancalagon.contracts.outcome_kind import OutcomeKind


class Exhausted(pydantic.BaseModel, typing.Generic[OutT], frozen=True):
    kind: typing.Literal[OutcomeKind.EXHAUSTED] = OutcomeKind.EXHAUSTED
    value: OutT
    summary: str
    spent: Budget
