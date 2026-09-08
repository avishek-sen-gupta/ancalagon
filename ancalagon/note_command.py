# The note subcommand: leaves an instruction a running task reads at its next turn.
import pathlib
import sys

from ancalagon.clock.system_clock import SystemClock
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.note import note_task


def note_command(run_dir: pathlib.PurePath, agent: int, text: str) -> int:
    task_dir = note_task(run_dir, agent, text, SystemClock(), RealFileSystem())
    sys.stdout.write(f"noted for task {task_dir}; delivered on that task's next turn\n")
    return 0
