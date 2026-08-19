# An attempt whose process the supervisor spawned and has not yet reaped.
import pydantic


class Running(pydantic.BaseModel, frozen=True):
    pid: int
