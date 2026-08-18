# The ways an attempt can end, and the adapter that parses one against a resolved class.
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.timed_out import TimedOut

# How much of an answer or a question is quoted into an outcome's summary.
SUMMARY_CHARS = 200

Outcome = (
    Completed[pydantic.BaseModel]
    | Exhausted[pydantic.BaseModel]
    | NeedsInput
    | Failed
    | TimedOut
    | Idling
)


def outcome_adapter(cls: type[pydantic.BaseModel]) -> pydantic.TypeAdapter[Outcome]:
    return pydantic.TypeAdapter(
        Completed[cls] | Exhausted[cls] | NeedsInput | Failed | TimedOut | Idling
    )
