# Arguments for surveying the size and shape of a codebase.
import pathlib

import pydantic


class StatsArgs(pydantic.BaseModel, frozen=True):
    roots: list[pathlib.PurePath]
    by_file: bool = False
