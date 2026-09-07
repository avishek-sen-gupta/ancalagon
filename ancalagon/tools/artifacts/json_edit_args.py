# Arguments for one in-place edit of a JSON file.
import pathlib

import pydantic

from ancalagon.tools.artifacts.json_op import JsonOp


class JsonEditArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.PurePath
    op: JsonOp
    pointer: str = pydantic.Field(
        pattern="^(/[^/]*)*$",
        description="RFC 6901 JSON Pointer, e.g. /values/0/name. Empty means the whole document.",
    )
    value: str = pydantic.Field(
        default="",
        description="The JSON text to write, e.g. '\"text\"', '42' or '{\"a\": 1}'. "
        "Leave empty for remove.",
    )
