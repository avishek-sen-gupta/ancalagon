import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.bus.task_status import TaskStatus


def test_bus_enqueues_claims_once_and_advances_cursor(tmp_path: pathlib.Path):
    db = tmp_path / "bus.db"
    bus = Bus.open(db)
    other = Bus.open(db)

    first = bus.enqueue(pathlib.Path("ws/tasks/a"), parent=0)
    second = bus.enqueue(pathlib.Path("ws/tasks/b"), parent=first)
    assert bus.get(first).status is TaskStatus.QUEUED
    assert bus.get(second).parent == first

    claimed = bus.claim(limit=10)
    assert sorted(t.id for t in claimed) == [first, second]
    assert other.claim(limit=10) == []

    bus.mark_running(first, pid=4242)
    assert bus.get(first).pid == 4242
    assert [t.id for t in bus.running()] == [first, second]
    assert bus.get(second).pid == 0

    bus.finish(first, TaskStatus.COMPLETED, exit_code=0, summary="done")
    finished = bus.get(first)
    assert finished.status is TaskStatus.COMPLETED
    assert finished.summary == "done"
    assert finished.finished != ""
    assert [t.id for t in bus.running()] == [second]

    bus.finish(second, TaskStatus.CRASHED, exit_code=1, summary="died")
    assert bus.running() == []

    bus.post(sender=first, addressee=0, kind="task_done", summary="done", ref_path="ws/tasks/a")
    inbox = bus.inbox(consumer=0)
    assert [m.kind for m in inbox] == ["task_done"]
    assert inbox[0].sender == first
    assert bus.inbox(consumer=0) == []
