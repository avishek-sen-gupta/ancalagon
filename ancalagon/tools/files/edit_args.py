import pathlib

import pydantic


class EditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    old: str
    new: str
