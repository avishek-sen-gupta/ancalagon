import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class Completed[OutT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.COMPLETED] = OutcomeKind.COMPLETED
    value: OutT
    summary: str
    spent: Budget
