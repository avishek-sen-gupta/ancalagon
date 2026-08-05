# Arguments for asking git what happened to a path.
import pathlib

import pydantic

from ancalagon.tools.history.git_operation import GitOperation


class HistoryArgs(pydantic.BaseModel, frozen=True):
    path: pathlib.Path
    operation: GitOperation = GitOperation.LOG
    rev: str = pydantic.Field(default="", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/~^-]*$|^$")
    limit: int = 20
