# Arguments for reading a slice of a file.
import pathlib

import pydantic


class ReadArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    offset: int = 0
    limit: int = 0
