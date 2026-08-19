# An attempt a supervisor has claimed but not yet spawned.
import pydantic


class Claimed(pydantic.BaseModel, frozen=True):
    pass
