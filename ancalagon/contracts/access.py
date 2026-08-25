# One record of an agent opening a file: what it read, and when that file had last changed.
import pydantic


class Access(pydantic.BaseModel, frozen=True):
    ts: str
    agent: int
    path: str
    mtime: float
