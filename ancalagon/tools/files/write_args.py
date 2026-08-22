import pathlib

import pydantic


class WriteArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    content: str
