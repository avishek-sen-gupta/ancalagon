# One claim's backing: a file, the lines it was read at, and those lines quoted verbatim.
import pydantic


class Evidence(pydantic.BaseModel, frozen=True):
    path: str = pydantic.Field(
        pattern=r"^/", description="Absolute path of the file, exactly as it was read."
    )
    start_line: int = pydantic.Field(
        ge=1, description="First line of the cited range, as read_file numbered it."
    )
    end_line: int = pydantic.Field(
        ge=1, description="Last line of the cited range, inclusive, as read_file numbered it."
    )
    quote: str = pydantic.Field(
        description="Those lines copied verbatim, one per line, nothing added or elided, "
        "without the line-number prefix read_file printed."
    )
