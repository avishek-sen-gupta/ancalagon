import pathlib

import pydantic


class SedArgs(pydantic.BaseModel, frozen=True):
    script: str
    path: pathlib.Path
