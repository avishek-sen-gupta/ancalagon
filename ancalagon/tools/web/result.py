# One result from a web search.
import pydantic


class Result(pydantic.BaseModel, frozen=True):
    rank: int
    title: str
    url: str
    snippet: str
