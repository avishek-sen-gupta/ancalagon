import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Failed(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["failed"] = OutcomeKind.FAILED.value
    error: str
    summary: str
    spent: Spend
