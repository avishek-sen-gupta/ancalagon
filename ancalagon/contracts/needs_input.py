import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class NeedsInput(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[OutcomeKind.NEEDS_INPUT] = OutcomeKind.NEEDS_INPUT
    question: str
    summary: str
    spent: Spend
