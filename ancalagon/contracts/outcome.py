# The ways an attempt can end, whatever produced it.
import typing

import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.needs_input import NeedsInput

SUMMARY_CHARS = 200
type Outcome[OutT: pydantic.BaseModel] = typing.Annotated[
    Completed[OutT] | Exhausted[OutT] | NeedsInput | Failed | Idling,
    pydantic.Field(discriminator="kind"),
]
