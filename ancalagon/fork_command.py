# The fork subcommand: a new run directory holding another run's history up to a chosen message.
import pathlib
import sys

from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.fork import forked, orphaned
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.run_dir import created_run_dir
from ancalagon.tools.delegate.delegating import delegate_name
from ancalagon.transcript.history import load

ROOT = pathlib.PurePath("tasks") / "root" / "transcript.jsonl"


def fork_run(
    config_path: pathlib.PurePath,
    source: pathlib.PurePath,
    at: int,
    clock: Clock,
    fs: FileSystem,
) -> tuple[pathlib.PurePath, tuple[str, ...]]:
    config = load_config(config_path, fs)
    history = source / ROOT
    if not fs.is_file(history):
        raise ValueError(f"--from {source} has no root transcript at {history}")
    delegates = frozenset(delegate_name(role) for role in config.roles)
    cut = forked(load(fs, history), at, delegates, clock)
    run_dir = created_run_dir("", config.home, clock, fs)
    fs.mkdir((run_dir / ROOT).parent, parents=True, exist_ok=True)
    fs.write_text(run_dir / ROOT, "".join(message.model_dump_json() + "\n" for message in cut))
    return run_dir, orphaned(cut, delegates)


def fork_command(config_path: pathlib.PurePath, source: pathlib.PurePath, at: int) -> int:
    run_dir, orphans = fork_run(config_path, source, at, SystemClock(), RealFileSystem())
    if orphans:
        sys.stderr.write(
            f"forked past a delegate; the history now says these tasks are not in this "
            f"run: {', '.join(orphans)}\n"
        )
    sys.stdout.write(f"{run_dir}\n")
    return 0
