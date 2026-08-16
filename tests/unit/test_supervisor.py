import json
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.clock.system_clock import SystemClock
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.supervisor.supervisor import Supervisor
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner
from ancalagon.clock.fake_clock import FakeClock


class FakeProcess(Process):
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


class FakeSpawner(Spawner):
    def __init__(self, script: list[tuple[int, int]]):
        self.script = list(script)
        self.spawned: list[int] = []

    def spawn(self, task_dir: pathlib.Path, agent_id: int) -> FakeProcess:
        self.spawned.append(agent_id)
        exit_after, code = self.script.pop(0)
        return FakeProcess(pid=1000 + agent_id, exit_after=exit_after, code=code)


def test_supervisor_completes_reports_crashes_and_kills_wedged_tasks(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    good = bus.enqueue(tmp_path / "tasks" / "good", parent_agent=0)
    bad = bus.enqueue(tmp_path / "tasks" / "bad", parent_agent=0)
    wedged = bus.enqueue(tmp_path / "tasks" / "wedged", parent_agent=0)

    spawner = FakeSpawner([(0, 0), (0, 1), (10_000, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.run_until_idle()

    assert spawner.spawned == [good, bad, wedged]
    assert bus.state(good).status is AgentStatus.EXITED
    assert bus.state(good).exit_code == 0
    assert bus.state(bad).status is AgentStatus.CRASHED
    assert bus.state(bad).exit_code == 1
    assert bus.state(wedged).status is AgentStatus.TIMED_OUT
    assert [e.pid for e in bus.history(wedged) if e.pid][0] == 1000 + wedged
    timed_out = json.loads((tmp_path / "tasks" / "wedged" / "outcome.json").read_text())
    assert timed_out["kind"] == "timed_out"
    assert bus.live() == []


def test_supervisor_respects_concurrency_cap_and_abandons_live_tasks_on_shutdown(
    tmp_path: pathlib.Path,
):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    ids = [bus.enqueue(tmp_path / "tasks" / f"t{i}", parent_agent=0) for i in range(3)]

    spawner = FakeSpawner([(10_000, 0)] * 3)
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=1_000_000, poll_s=1.0, clock=clock
    )

    supervisor.tick()
    assert spawner.spawned == ids[:2]
    assert len(supervisor.live) == 2
    assert [s.agent for s in bus.in_flight()] == ids[:2]

    supervisor.shutdown()
    assert supervisor.live == {}
    assert bus.state(ids[0]).status is AgentStatus.ABANDONED
    assert bus.state(ids[1]).status is AgentStatus.ABANDONED
    assert bus.state(ids[2]).status is AgentStatus.QUEUED
