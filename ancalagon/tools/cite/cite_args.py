# What a citation needs from the model: where it looked, what it read there, and what it means.
import typing  # type-hygiene: other_data

import pydantic

from ancalagon.contracts.source_span import SourceSpan


class CiteArgs(SourceSpan, frozen=True):
    quote: str = pydantic.Field(
        description="The cited text copied verbatim from those lines, without the "
        "line-number prefix read_file printed. It is checked against the file."
    )
    note: str = pydantic.Field(min_length=1, description="What this span shows, in your own words.")
    other_data: dict[str, typing.Any] = pydantic.Field(  # type-hygiene: other_data
        default={},
        description="Anything else worth keeping with this citation, as a JSON object. "
        "Its shape is yours to choose and nothing validates it.",
    )
