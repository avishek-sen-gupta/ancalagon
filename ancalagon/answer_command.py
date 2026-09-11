# The answer subcommand: unsticks an agent that stopped with a question.
import pathlib
import sys

from ancalagon.answer import answer_task
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.fs.real_file_system import RealFileSystem


def answer_command(run_dir: pathlib.PurePath, agent: int, answer: str) -> int:
    fs = RealFileSystem()
    clock = SystemClock()
    bus = LifecycleStore.open(run_dir / "bus.db", clock, fs)
    resumed = answer_task(bus, agent, answer, answered_by=HUMAN, clock=clock, fs=fs)
    sys.stdout.write(f"answered agent {agent}; queued agent {resumed.id}\n")
    return 0
