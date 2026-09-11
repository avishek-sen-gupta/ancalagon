import pathlib

import pytest

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.letterbox.file_letterbox import FileLetterbox
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.note import note_task
from ancalagon.note_command import note_command


def _running(tmp_path: pathlib.Path) -> tuple[pathlib.PurePath, int, pathlib.PurePath]:
    run_dir = pathlib.PurePath(tmp_path / "run")
    task_dir = run_dir / "tasks" / "working"
    RealFileSystem().mkdir(task_dir, parents=True)
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), RealFileSystem())
    return run_dir, bus.enqueue(task_dir, parent_agent=0).id, task_dir


def test_a_note_lands_in_the_letterbox_of_the_task_the_agent_belongs_to(tmp_path: pathlib.Path):
    run_dir, agent, task_dir = _running(tmp_path)
    box = FileLetterbox(RealFileSystem(), task_dir)

    noted = note_task(
        run_dir, agent, "send the nested fields as objects", SystemClock(), RealFileSystem()
    )
    assert noted == task_dir

    note_task(run_dir, agent, "and read the definition first", SystemClock(), RealFileSystem())
    assert box.unread() == ("send the nested fields as objects", "and read the definition first")

    with pytest.raises(KeyError):
        note_task(run_dir, 99, "nobody", SystemClock(), RealFileSystem())


def test_the_command_refuses_empty_text_and_names_the_task_it_noted(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    run_dir, agent, task_dir = _running(tmp_path)
    box = FileLetterbox(RealFileSystem(), task_dir)

    with pytest.raises(ValueError, match="a note needs text"):
        note_command(run_dir, agent, "   ")
    assert box.unread() == ()

    assert note_command(run_dir, agent, "stop guessing the shape") == 0
    assert f"noted for task {task_dir}" in capsys.readouterr().out
    assert box.unread() == ("stop guessing the shape",)
