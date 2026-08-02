import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class NeedsInput(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.NEEDS_INPUT] = OutcomeKind.NEEDS_INPUT
    question: str
    summary: str
    spent: Budget
