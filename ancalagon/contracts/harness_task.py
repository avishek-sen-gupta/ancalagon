# A unit of work, identified by its directory; agents are attempts at it.
import pydantic


class HarnessTask(pydantic.BaseModel, frozen=True):
    id: int
    dir: str
    parent_agent: int
    created: str
