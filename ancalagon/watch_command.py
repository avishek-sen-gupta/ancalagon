# The watch subcommand: follows every agent in a workspace as it works. Not the watch_file tool.
import pathlib
import shutil
import sys

from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.watching.watch import Watch

FRAME = 9
FLOOR = 20


def _width(label_room: int) -> int:
    return max(FLOOR, shutil.get_terminal_size().columns - label_room - FRAME)


def watching(config_path: pathlib.PurePath, fs: FileSystem, clock: Clock) -> Watch:
    config = load_config(config_path, fs)
    return Watch(config.write_root, fs, clock, _width(len(str(config.write_root))))


def watch_command(config_path: pathlib.PurePath, interval_s: float) -> int:
    fs = RealFileSystem()
    clock = SystemClock()
    watch = watching(config_path, fs, clock)
    sys.stderr.write(f"-- watching {watch.write_root}, existing history not replayed --\n")
    while True:
        sys.stdout.write(watch.tick())
        sys.stdout.flush()
        clock.sleep(interval_s)
