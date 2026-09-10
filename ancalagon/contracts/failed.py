import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class Failed(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.FAILED] = OutcomeKind.FAILED
    error: str
    summary: str
    spent: Spend
