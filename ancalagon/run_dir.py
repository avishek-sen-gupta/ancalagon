# Where a run's directory comes from: the one it was given, or a fresh one under home.
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.fs.file_system import FileSystem

STAMP = "r_%Y%m%d-%H%M%S"


def _allocated_run_dir(home: pathlib.PurePath, clock: Clock, fs: FileSystem) -> pathlib.PurePath:
    runs = home / "runs"
    fs.mkdir(runs, parents=True, exist_ok=True)
    return runs / clock.now().strftime(STAMP)


def created_run_dir(
    run_dir: str, home: pathlib.PurePath, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    if run_dir:
        named = pathlib.PurePath(run_dir)
        fs.mkdir(named, parents=True, exist_ok=True)
        return named
    allocated = _allocated_run_dir(home, clock, fs)
    fs.mkdir(allocated, parents=True)
    return allocated
