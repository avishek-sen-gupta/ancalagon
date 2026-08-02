import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class Failed(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.FAILED] = OutcomeKind.FAILED
    error: str
    summary: str
    spent: Budget
