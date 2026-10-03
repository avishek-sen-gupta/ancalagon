import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Completed[OutT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    kind: typing.Literal["completed"] = OutcomeKind.COMPLETED.value
    value: OutT
    summary: str
    spent: Spend
