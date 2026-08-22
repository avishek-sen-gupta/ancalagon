# Arguments for pulling readable text out of a binary.
import pathlib

import pydantic


class StringsArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    min_length: int = 6
