# The part of a file a claim points at: a line and column range, both inclusive.
import pydantic


class SourceSpan(pydantic.BaseModel, frozen=True):
    path: str = pydantic.Field(
        pattern=r"^/", description="Absolute path of the file, exactly as it was read."
    )
    start_line: int = pydantic.Field(
        ge=1, description="First line of the span, as read_file numbered it."
    )
    end_line: int = pydantic.Field(
        ge=1, description="Last line of the span, inclusive, as read_file numbered it."
    )
    start_column: int = pydantic.Field(
        ge=1, description="Column the span starts at on its first line, counting from 1."
    )
    end_column: int = pydantic.Field(
        ge=1, description="Column the span ends at on its last line, inclusive, counting from 1."
    )
