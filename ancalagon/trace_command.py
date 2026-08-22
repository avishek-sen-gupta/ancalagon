# The trace subcommand: reads a finished or running run and emits its graph as JSON.
import collections.abc
import pathlib

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.message import Message
from ancalagon.emit import emit
from ancalagon.fs.file_system import FileSystem
from ancalagon.trace.graph_of import graph_of
from ancalagon.transcript.history import load

TRANSCRIPT = "transcript.jsonl"


def _messages(
    snapshot: Snapshot, fs: FileSystem
) -> collections.abc.Mapping[int, collections.abc.Sequence[Message]]:
    found = {
        task.id: pathlib.PurePath(task.dir) / TRANSCRIPT
        for task in snapshot.tasks
        if fs.is_file(pathlib.PurePath(task.dir) / TRANSCRIPT)
    }
    return {task: load(fs, path) for task, path in found.items()}


def trace_command(run_dir: pathlib.PurePath, output: str, fs: FileSystem) -> int:
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs)
    snapshot = bus.snapshot()
    emit(graph_of(snapshot, _messages(snapshot, fs)).model_dump_json(), output, fs)
    return 0
