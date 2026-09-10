import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Exhausted[OutT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.EXHAUSTED] = OutcomeKind.EXHAUSTED
    value: OutT
    summary: str
    spent: Spend
