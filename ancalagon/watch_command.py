# The watch subcommand: follows every agent in a workspace as it works. Not the watch_file tool.
import pathlib
import shutil
import sys

from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.watching.watch import TRANSCRIPTS, Watch

UNSET = ""


def concern(write_root: pathlib.PurePath, fs: FileSystem) -> str:
    if fs.is_dir(write_root / "runs") or _agents_under(write_root, fs):
        return ""
    return f"nothing to watch under {write_root}; is this the write_root?"


def _agents_under(write_root: pathlib.PurePath, fs: FileSystem) -> bool:
    return any(fs.glob(write_root, shape) for shape in TRANSCRIPTS)


def _root(config_path: str, watch_dir: str, fs: FileSystem) -> pathlib.PurePath:
    if watch_dir:
        return fs.resolve(pathlib.PurePath(watch_dir))
    return load_config(pathlib.PurePath(config_path), fs).write_root


def watching(config_path: str, watch_dir: str, fs: FileSystem, clock: Clock) -> Watch:
    root = _root(config_path, watch_dir, fs)
    return Watch(root, fs, clock, shutil.get_terminal_size().columns)


def watch_command(config_path: str, watch_dir: str, interval_s: float) -> int:
    fs = RealFileSystem()
    clock = SystemClock()
    watch = watching(config_path, watch_dir, fs, clock)
    doubt = concern(watch.write_root, fs)
    if doubt:
        sys.stderr.write(f"-- {doubt} --\n")
    sys.stderr.write(f"-- watching {watch.write_root}, existing history not replayed --\n")
    while True:
        sys.stdout.write(watch.tick())
        sys.stdout.flush()
        clock.sleep(interval_s)
