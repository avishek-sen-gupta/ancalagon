# Arguments for a web search.
import pydantic


class SearchArgs(pydantic.BaseModel, frozen=True):
    query: str
    count: int = pydantic.Field(default=10, ge=1, le=25)
