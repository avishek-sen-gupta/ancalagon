# What an attempt returns when it stops to wait for its children.
import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.outcome_kind import OutcomeKind


class Idling(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.IDLING] = OutcomeKind.IDLING
    summary: str
    spent: Budget
