# A range of lines in one file, as the model names it: both ends inclusive, counted from one.
import pathlib

import pydantic


class Region(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    start_line: int = pydantic.Field(ge=1, description="First line of the range.")
    end_line: int = pydantic.Field(ge=1, description="Last line of the range, inclusive.")
