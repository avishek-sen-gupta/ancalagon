# The ways an attempt can end, and the adapter that parses one against a resolved class.
import pydantic

from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.timed_out import TimedOut

Outcome = (
    Completed[pydantic.BaseModel] | Exhausted[pydantic.BaseModel] | NeedsInput | Failed | TimedOut
)


def outcome_adapter(cls: type[pydantic.BaseModel]) -> pydantic.TypeAdapter[Outcome]:
    return pydantic.TypeAdapter(Completed[cls] | Exhausted[cls] | NeedsInput | Failed | TimedOut)
