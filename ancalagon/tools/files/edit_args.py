import pathlib

import pydantic


class EditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    old: str
    new: str
