import pathlib

import pydantic


class TransformArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    script: str = pydantic.Field(
        min_length=1,
        description=(
            "A sed script, for example 's/#.*//' to drop comments or '/^$/d' to drop blank "
            "lines. It shapes what you get back; it never touches the file."
        ),
    )
