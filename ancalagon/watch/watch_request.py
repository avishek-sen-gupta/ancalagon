# What a watcher is asked to wait for: a file, and the moment it was last known to change.
import pydantic


class WatchRequest(pydantic.BaseModel, frozen=True):
    path: str
    since: float = 0.0
    poll_s: float = 0.5
