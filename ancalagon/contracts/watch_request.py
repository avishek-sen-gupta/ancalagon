# What a watcher waits for: a file, and the moment its caller last saw it.
import pydantic


class WatchRequest(pydantic.BaseModel, frozen=True):
    path: str
    since: float = 0.0
    poll_s: float = 0.5
