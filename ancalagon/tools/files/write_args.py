import pathlib

import pydantic


class WriteArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    content: str
