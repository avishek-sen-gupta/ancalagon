# What a run function is given besides its input: the ports, and where this task lives.
import dataclasses
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.fs.file_system import FileSystem


@dataclasses.dataclass(frozen=True)
class RunContext:
    fs: FileSystem
    clock: Clock
    task_dir: pathlib.PurePath
    run_dir: pathlib.PurePath
