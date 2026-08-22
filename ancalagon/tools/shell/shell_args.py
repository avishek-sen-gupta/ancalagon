import pathlib

import pydantic


class ShellArgs(pydantic.BaseModel, frozen=True):
    command: str = pydantic.Field(
        description="A shell command line, run by /bin/sh. Pipes, globs and redirection work."
    )
    cwd: pathlib.PurePath = pydantic.Field(
        description="The directory to run in. Must be inside a read root."
    )
