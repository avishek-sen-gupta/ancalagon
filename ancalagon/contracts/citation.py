# One thing an agent noted about one span of one file, kept so a later turn need not re-read it.
import typing  # type-hygiene: other_data

import pydantic

from ancalagon.contracts.source_span import SourceSpan


class Citation(pydantic.BaseModel, frozen=True):
    ts: str
    agent: int
    span: SourceSpan
    quote: str
    note: str
    other_data: dict[str, typing.Any] = {}  # type-hygiene: other_data
