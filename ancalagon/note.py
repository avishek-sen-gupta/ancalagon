# Leaves a note in a task's letterbox, for whichever agent next runs that task to read.
import pathlib

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.clock import Clock
from ancalagon.fs.file_system import FileSystem
from ancalagon.letterbox.file_letterbox import NOTES, SUFFIX
from ancalagon.schedule.task_of import task_of

STAMP = "%Y%m%dT%H%M%S%f"


def note_task(
    run_dir: pathlib.PurePath, agent: int, text: str, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    if not text.strip():
        raise ValueError("a note needs text")
    bus = LifecycleStore.open(run_dir / "bus.db", clock, fs)
    task_dir = pathlib.PurePath(task_of(bus.snapshot(), agent).dir)
    notes = task_dir / NOTES
    fs.mkdir(notes, parents=True, exist_ok=True)
    fs.write_text(notes / f"{clock.now().strftime(STAMP)}{SUFFIX}", text)
    return task_dir
