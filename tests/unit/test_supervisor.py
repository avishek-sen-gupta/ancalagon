import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.bus.task_status import TaskStatus
from ancalagon.supervisor.supervisor import Supervisor


class FakeProcess:
    def __init__(self, pid: int, exit_after: int, code: int):
        self.pid = pid
        self.exit_after = exit_after
        self.code = code
        self.polls = 0
        self.killed = False

    def poll(self) -> int | None:
        self.polls += 1
        if self.killed:
            return -9
        return self.code if self.polls > self.exit_after else None

    def kill(self) -> None:
        self.killed = True


class FakeSpawner:
    def __init__(self, script: list[tuple[int, int]]):
        self.script = list(script)
        self.spawned: list[int] = []

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> FakeProcess:
        self.spawned.append(agent_id)
        exit_after, code = self.script.pop(0)
        return FakeProcess(pid=1000 + agent_id, exit_after=exit_after, code=code)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_supervisor_completes_reports_crashes_and_kills_wedged_tasks(tmp_path: pathlib.Path):
    bus = Bus.open(tmp_path / "bus.db")
    good = bus.enqueue(tmp_path / "tasks" / "good", parent=0)
    bad = bus.enqueue(tmp_path / "tasks" / "bad", parent=0)
    wedged = bus.enqueue(tmp_path / "tasks" / "wedged", parent=0)

    spawner = FakeSpawner([(0, 0), (0, 1), (10_000, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.run_until_idle()

    assert spawner.spawned == [good, bad, wedged]
    assert bus.get(good).status is TaskStatus.COMPLETED
    assert bus.get(good).exit_code == 0
    assert bus.get(bad).status is TaskStatus.CRASHED
    assert bus.get(bad).exit_code == 1
    assert bus.get(wedged).status is TaskStatus.TIMEOUT
    assert bus.get(wedged).pid == 1000 + wedged
    assert bus.running() == []
    assert [m.kind for m in bus.inbox(consumer=0)] == ["task_done"] * 3


def test_supervisor_respects_concurrency_cap_and_abandons_live_tasks_on_shutdown(
    tmp_path: pathlib.Path,
):
    bus = Bus.open(tmp_path / "bus.db")
    ids = [bus.enqueue(tmp_path / "tasks" / f"t{i}", parent=0) for i in range(3)]

    spawner = FakeSpawner([(10_000, 0)] * 3)
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=1_000_000, poll_s=1.0, clock=clock
    )

    supervisor.tick()
    assert spawner.spawned == ids[:2]
    assert len(supervisor.live) == 2
    assert [t.id for t in bus.running()] == ids[:2]

    supervisor.shutdown()
    assert supervisor.live == {}
    assert bus.get(ids[0]).status is TaskStatus.ABANDONED
    assert bus.get(ids[1]).status is TaskStatus.ABANDONED
    assert bus.get(ids[2]).status is TaskStatus.QUEUED
