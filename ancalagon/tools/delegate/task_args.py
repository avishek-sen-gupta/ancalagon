import pydantic


class TaskArgs(pydantic.BaseModel, frozen=True):
    task: int
