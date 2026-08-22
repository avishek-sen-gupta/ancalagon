# Arguments for locating where a symbol is defined.
import pathlib

import pydantic


class SymbolArgs(pydantic.BaseModel, frozen=True):
    roots: list[pathlib.PurePath]
    name: str = ""
