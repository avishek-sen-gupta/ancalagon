# Arguments for querying a JSON file.
import pathlib

import pydantic


class QueryArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    filter: str = "."
