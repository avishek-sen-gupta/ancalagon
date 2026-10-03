# What an attempt returns when it stops to wait for its children.
import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Idling(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["idling"] = OutcomeKind.IDLING.value
    summary: str
    spent: Spend
    seen_through: int
