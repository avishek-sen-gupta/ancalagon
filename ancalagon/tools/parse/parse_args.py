import pathlib

import pydantic


class ParseArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    language: str
