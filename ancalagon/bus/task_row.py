# One row of the tasks table.
import pydantic

from ancalagon.bus.task_status import TaskStatus


class TaskRow(pydantic.BaseModel, frozen=True):
    id: int
    dir: str
    parent: int
    status: TaskStatus
    pid: int
    exit_code: int
    summary: str
    started: str
    finished: str
