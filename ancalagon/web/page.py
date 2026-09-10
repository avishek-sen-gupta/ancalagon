# One HTTP response, as the harness sees it.
import pydantic


class Page(pydantic.BaseModel, frozen=True):
    url: str
    status: int
    content_type: str
    body: str
