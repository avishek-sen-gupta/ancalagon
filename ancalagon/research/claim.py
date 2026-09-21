# A statement in a report, with the pages that support it.
import pydantic


class Claim(pydantic.BaseModel, frozen=True):
    statement: str
    urls: tuple[str, ...]
    verified: bool
