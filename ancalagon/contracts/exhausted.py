import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class Exhausted[OutT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.EXHAUSTED] = OutcomeKind.EXHAUSTED
    value: OutT
    summary: str
    spent: Budget
