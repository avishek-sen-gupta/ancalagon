import pathlib

import pydantic


class WatchArgs(pydantic.BaseModel, frozen=True):
    task_id: str = pydantic.Field(
        description="A new id for the watching task. Reusing a finished one retries it."
    )
    path: pathlib.PurePath = pydantic.Field(
        description="The file to wait on. You are woken once it grows beyond its size right now."
    )
