# A single path argument, for tools that inspect one artifact.
import pathlib

import pydantic


class PathArg(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
