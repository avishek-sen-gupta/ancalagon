# An attempt enqueued but not yet claimed by any supervisor.
import pydantic


class Queued(pydantic.BaseModel, frozen=True):
    pass
