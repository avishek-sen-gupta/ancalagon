# What a citation needs from the model: where it looked, what it read there, and what it means.
import pydantic

from ancalagon.contracts.source_span import SourceSpan


class CiteArgs(SourceSpan, frozen=True):
    quote: str = pydantic.Field(
        description="The cited text copied verbatim from those lines, without the "
        "line-number prefix read_file printed. It is checked against the file."
    )
    note: str = pydantic.Field(min_length=1, description="What this span shows, in your own words.")
