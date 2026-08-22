# Arguments for a text or structural search.
import pathlib

import pydantic


class GrepArgs(pydantic.BaseModel, frozen=True):
    pattern: str
    roots: list[pathlib.PurePath]
    structured: bool = False
