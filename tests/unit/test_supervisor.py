import json
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.clock.system_clock import SystemClock
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.event_source import EventSource
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


def test_a_crash_leaves_the_outcome_a_parent_needs_to_collect(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    died = bus.enqueue(tmp_path / "tasks" / "died", parent_agent=0)
    spoke = bus.enqueue(tmp_path / "tasks" / "spoke", parent_agent=0)
    (tmp_path / "tasks" / "spoke").mkdir(parents=True)
    (tmp_path / "tasks" / "spoke" / "outcome.json").write_text('{"kind": "its own"}')

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([(0, 3), (0, 3)]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=FakeClock(),
    ).tick()

    assert bus.state(died).status is AgentStatus.CRASHED
    assert bus.state(spoke).status is AgentStatus.CRASHED
    assert json.loads((tmp_path / "tasks" / "died" / "outcome.json").read_text()) == {
        "kind": "failed",
        "error": "worker exited 3",
        "summary": "worker exited 3",
        "spent": {"turns": 0, "tool_calls": 0},
    }
    assert json.loads((tmp_path / "tasks" / "spoke" / "outcome.json").read_text()) == {
        "kind": "its own"
    }


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
    assert [s.agent for s in bus.unreaped()] == ids[:2]

    supervisor.shutdown()
    assert supervisor.live == {}
    assert bus.state(ids[0]).status is AgentStatus.ABANDONED
    assert bus.state(ids[1]).status is AgentStatus.ABANDONED
    assert bus.state(ids[2]).status is AgentStatus.QUEUED


def test_an_agent_whose_own_status_nobody_reaped_is_swept_as_orphaned(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    done = bus.enqueue(tmp_path / "tasks" / "done", parent_agent=0)
    idled = bus.enqueue(tmp_path / "tasks" / "idled", parent_agent=0)
    reaped = bus.enqueue(tmp_path / "tasks" / "reaped", parent_agent=0)
    for agent in (done, idled, reaped):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)
    bus.record(done, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(idled, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(reaped, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(reaped, AgentStatus.EXITED, EventSource.SUPERVISOR)

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=FakeClock(),
    ).run_until_idle()

    assert [s.agent for s in bus.unreaped()] == []
    assert bus.state(done).status is AgentStatus.ABANDONED
    assert bus.state(idled).status is AgentStatus.ABANDONED
    assert bus.state(reaped).status is AgentStatus.EXITED


def test_a_tick_wakes_an_idling_parent_once_its_childs_process_is_gone(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    parent_dir = tmp_path / "tasks" / "parent"
    parent = bus.enqueue(parent_dir, parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=parent)

    spawner = FakeSpawner([(0, 0), (0, 0), (10, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.tick()
    assert bus.state(parent).status is AgentStatus.EXITED
    assert bus.state(child).status is AgentStatus.EXITED

    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)

    bus.record(child, AgentStatus.COMPLETED, EventSource.WORKER)
    supervisor.live[child] = FakeProcess(pid=1000 + child, exit_after=100, code=0)
    supervisor.started[child] = clock.time()
    supervisor.tick()
    assert [s for s in bus.live() if s.dir == str(parent_dir)] == []

    del supervisor.live[child]
    del supervisor.started[child]
    bus.record(child, AgentStatus.EXITED, EventSource.SUPERVISOR)

    supervisor.tick()

    resumed = [s for s in bus.live() if s.dir == str(parent_dir)]
    assert len(resumed) == 1
    assert resumed[0].agent != parent

    supervisor.tick()
    assert len([s for s in bus.live() if s.dir == str(parent_dir)]) == 1


def test_a_wake_is_skipped_while_the_idling_agents_process_is_still_live(
    tmp_path: pathlib.Path,
):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    parent_dir = tmp_path / "tasks" / "parent"
    parent = bus.enqueue(parent_dir, parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=parent)
    parent_task = bus.state(parent).task

    def agents_for(task_id: int) -> list[int]:
        rows = bus.conn.execute("SELECT id FROM agents WHERE task = ?", (task_id,)).fetchall()
        return [int(r["id"]) for r in rows]

    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=FakeSpawner([]), max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    bus.record(parent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(parent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)
    supervisor.live[parent] = FakeProcess(pid=4242, exit_after=100, code=0)
    supervisor.started[parent] = clock.time()
    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)

    bus.record(child, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(child, AgentStatus.EXITED, EventSource.SUPERVISOR)

    supervisor.tick()
    assert agents_for(parent_task) == [parent]

    del supervisor.live[parent]
    supervisor.tick()
    assert len(agents_for(parent_task)) == 2
