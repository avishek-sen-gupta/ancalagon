import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class TimedOut(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.TIMED_OUT] = OutcomeKind.TIMED_OUT
    summary: str
    spent: Budget
