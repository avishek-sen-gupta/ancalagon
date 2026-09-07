# One claim's backing: a file, the lines it was read at, and those lines quoted verbatim.
import pydantic


class Evidence(pydantic.BaseModel, frozen=True):
    path: str = pydantic.Field(
        pattern=r"^/", description="Absolute path of the file, exactly as it was read."
    )
    start_line: int = pydantic.Field(ge=1, description="First line of the cited range.")
    end_line: int = pydantic.Field(ge=1, description="Last line of the cited range, inclusive.")
    quote: str = pydantic.Field(
        description="Those lines copied verbatim, one per line, nothing added or elided."
    )
