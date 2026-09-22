# One thing an agent noted about one span of one file, kept so a later turn need not re-read it.
import pydantic

from ancalagon.contracts.source_span import SourceSpan


class Citation(pydantic.BaseModel, frozen=True):
    ts: str
    agent: int
    span: SourceSpan
    quote: str
    note: str
