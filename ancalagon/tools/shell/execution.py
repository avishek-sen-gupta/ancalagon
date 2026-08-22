# What a shell command that ran to completion left behind.
import pydantic


class Execution(pydantic.BaseModel, frozen=True):
    exit_code: int
    stdout: str
    stderr: str
