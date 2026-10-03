import typing

import pydantic

from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.spend import Spend


class NeedsInput(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["needs_input"] = OutcomeKind.NEEDS_INPUT.value
    question: str
    summary: str
    spent: Spend
