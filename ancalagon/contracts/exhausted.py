import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Exhausted[OutT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    kind: typing.Literal["exhausted"] = OutcomeKind.EXHAUSTED.value
    value: OutT
    summary: str
    spent: Spend
