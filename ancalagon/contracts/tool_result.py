import pathlib

import pydantic


class ToolResult(pydantic.BaseModel, frozen=True):
    ok: bool
    summary: str
    path: pathlib.Path
    byte_count: int = 0
    truncated: bool = False
    error: str = ""
