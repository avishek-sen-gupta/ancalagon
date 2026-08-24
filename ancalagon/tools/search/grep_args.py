# Arguments for a text or structural search.
import pathlib

import pydantic


class GrepArgs(pydantic.BaseModel, frozen=True):
    pattern: str
    roots: list[pathlib.PurePath]
    structured: bool = False
    globs: list[str] = pydantic.Field(
        default=[],
        description=(
            "Restrict the search to files matching these globs, for example ['*.py']. "
            "Prefix a glob with ! to exclude instead, for example ['*.py', '!test_*']. "
            "Omit to search every file under the roots."
        ),
    )
