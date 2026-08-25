import pathlib

import pydantic


class AppendArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    content: str = pydantic.Field(
        description="One entry, written as its own line. Newlines inside it make several."
    )
