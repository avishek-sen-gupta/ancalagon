# One line of a run's log, named so a queue reader needs no run directory.
import pydantic

from ancalagon.contracts.line import Line


class LogEvent(pydantic.BaseModel, frozen=True):
    run: str
    task: str
    at: str
    line: Line = pydantic.Field(discriminator="kind")
