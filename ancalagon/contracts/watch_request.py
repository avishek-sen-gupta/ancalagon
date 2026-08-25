# What a watcher is asked to wait for: a file, and how much of it the caller had already seen.
import pydantic


class WatchRequest(pydantic.BaseModel, frozen=True):
    path: str
    seen_bytes: int = 0
    poll_s: float = 0.5
