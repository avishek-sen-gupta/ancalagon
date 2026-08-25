import pathlib

import pydantic


class WatchArgs(pydantic.BaseModel, frozen=True):
    task_id: str = pydantic.Field(
        description=(
            "A name for your waiting task. Yours alone: your own task name is added to it, "
            "so another agent choosing the same name still gets its own watcher."
        )
    )
    path: pathlib.PurePath = pydantic.Field(
        description="The file to wait on. You are woken once it changes after you last read it."
    )
