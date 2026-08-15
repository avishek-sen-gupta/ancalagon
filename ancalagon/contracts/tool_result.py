# What every tool returns: a payload the caller reads, and a path to the full output.
import pathlib

import pydantic

from ancalagon.contracts.payload import Payload


class ToolResult(pydantic.BaseModel, frozen=True):
    ok: bool
    summary: Payload
    path: pathlib.Path
    byte_count: int = 0
    truncated: bool = False
    error: str = ""
