# Arguments for reading a slice of a file.
import pathlib

import pydantic


class ReadArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    offset: int = 0
    limit: int = 0
