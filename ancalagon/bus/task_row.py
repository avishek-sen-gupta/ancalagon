# One row of the tasks table: the work, identified by its directory.
import pydantic


class TaskRow(pydantic.BaseModel, frozen=True):
    id: int
    dir: str
    parent_agent: int
    created: str
