# A command the timeout killed, which has no exit code to report.
import pydantic


class TimedOut(pydantic.BaseModel, frozen=True):
    seconds: int
