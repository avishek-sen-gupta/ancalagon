# What a watcher reports: the file it waited on, and when that file changed.
import pydantic


class Watched(pydantic.BaseModel, frozen=True):
    path: str
    at: float
