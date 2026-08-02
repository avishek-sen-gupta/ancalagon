import pathlib

import pydantic


class PathArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
