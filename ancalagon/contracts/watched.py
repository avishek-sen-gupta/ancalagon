# What a watcher reports: the file it waited on, and how large it had become.
import pydantic


class Watched(pydantic.BaseModel, frozen=True):
    path: str
    size: int
