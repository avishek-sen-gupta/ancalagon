# The one field a delegate call's arguments are read for: which task it queued.
import pydantic


class DelegatedTask(pydantic.BaseModel, frozen=True):
    task_id: str
