import pathlib
import typing

from ancalagon.attempt.closed import Closed
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.queued import Queued
from ancalagon.attempt.running import Running
from ancalagon.bus.bus import HUMAN, Bus
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.role import Role
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.supervisor.fake_liveness import FakeLiveness
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner
from ancalagon.supervisor.supervisor import Supervisor
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate_to import DelegateTo
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.workspace import Workspace


def _open(tmp_path: pathlib.Path) -> Bus:
    db = tmp_path / "bus.db"
    migrate_file(db, latest_version())
    return Bus.open(db, FakeClock())


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    outputs = write_root / "outputs"
    outputs.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=outputs,
        summary_chars=50,
        agent_id=17,
    )


def _write_completed(task_dir: pathlib.Path) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "outcome.json").write_text(
        Completed[FreeText](
            value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=1)
        ).model_dump_json()
    )


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
    _write_completed(tmp_path / "tasks" / "spoke")

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([(0, 3), (0, 3)]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=FakeClock(),
    ).tick()

    assert bus.attempt(died) == Lost(close=AgentStatus.CRASHED)
    assert bus.attempt(spoke) == Closed(verdict=AgentStatus.COMPLETED)
    assert (tmp_path / "tasks" / "died" / "outcome.json").exists() is False


def test_supervisor_completes_reports_crashes_and_kills_wedged_tasks(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    good = bus.enqueue(tmp_path / "tasks" / "good", parent_agent=0)
    bad = bus.enqueue(tmp_path / "tasks" / "bad", parent_agent=0)
    wedged = bus.enqueue(tmp_path / "tasks" / "wedged", parent_agent=0)
    _write_completed(tmp_path / "tasks" / "good")

    spawner = FakeSpawner([(0, 0), (0, 1), (10_000, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.run_until_idle()

    assert spawner.spawned == [good, bad, wedged]
    assert bus.attempt(good) == Closed(verdict=AgentStatus.COMPLETED)
    assert bus.attempt(bad) == Lost(close=AgentStatus.CRASHED)
    assert bus.attempt(wedged) == Lost(close=AgentStatus.TIMED_OUT)
    assert [e.pid for e in bus.history(wedged) if e.pid][0] == 1000 + wedged
    assert (tmp_path / "tasks" / "wedged" / "outcome.json").exists() is False


def test_supervisor_respects_concurrency_cap_and_leaves_live_tasks_running_on_shutdown(
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
    processes = typing.cast(dict[int, FakeProcess], dict(supervisor.live))

    supervisor.shutdown()
    assert supervisor.live == {}
    assert all(not process.killed for process in processes.values())
    assert bus.state(ids[0]).status is AgentStatus.RUNNING
    assert bus.state(ids[1]).status is AgentStatus.RUNNING
    assert bus.state(ids[2]).status is AgentStatus.QUEUED

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=1_000_000,
        poll_s=1.0,
        clock=clock,
        liveness=FakeLiveness(frozenset()),
    ).resolve_stale()
    assert bus.state(ids[0]).status is AgentStatus.CRASHED
    assert bus.state(ids[1]).status is AgentStatus.CRASHED


def test_startup_resolves_agents_by_reading_the_outcome_a_worker_left(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    done = bus.enqueue(tmp_path / "tasks" / "done", parent_agent=0)
    silent = bus.enqueue(tmp_path / "tasks" / "silent", parent_agent=0)
    _write_completed(tmp_path / "tasks" / "done")
    for agent in (done, silent):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=FakeClock(),
        liveness=FakeLiveness(frozenset()),
    ).run_until_idle()

    assert [s.agent for s in bus.unreaped()] == []
    assert bus.attempt(done) == Closed(verdict=AgentStatus.COMPLETED)
    assert bus.attempt(silent) == Lost(close=AgentStatus.CRASHED)


def test_a_tick_wakes_an_idling_parent_once_a_supervisor_has_reaped_its_child(
    tmp_path: pathlib.Path,
):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    parent_dir = tmp_path / "tasks" / "parent"
    parent = bus.enqueue(parent_dir, parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=parent)

    spawner = FakeSpawner([(1, 0), (2, 0), (10, 0)])
    clock = FakeClock()
    supervisor = Supervisor(
        bus=bus, spawner=spawner, max_concurrent=2, timeout_s=5, poll_s=1.0, clock=clock
    )

    supervisor.tick()
    assert bus.attempt(parent) == Running(pid=1000 + parent)
    assert list(supervisor.live) == [parent, child]

    parent_dir.mkdir(parents=True, exist_ok=True)
    (parent_dir / "outcome.json").write_text(
        Idling(summary="waiting on children", spent=Budget(turns=1, tool_calls=1)).model_dump_json()
    )
    _write_completed(tmp_path / "tasks" / "child")

    supervisor.tick()
    assert bus.attempt(parent) == Closed(verdict=AgentStatus.IDLING)

    supervisor.tick()
    assert bus.attempt(child) == Closed(verdict=AgentStatus.COMPLETED)

    active = bus.active_for(parent_dir)
    assert len(active) == 1
    resumed = active[0].agent
    assert resumed != parent
    assert bus.attempt(resumed) == Queued()

    supervisor.tick()
    active_after = bus.active_for(parent_dir)
    assert len(active_after) == 1
    assert bus.attempt(resumed) == Running(pid=1000 + resumed)


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
    bus.record(parent, AgentStatus.IDLING, EventSource.SUPERVISOR)

    bus.record(child, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(child, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    bus.record(child, AgentStatus.COMPLETED, EventSource.SUPERVISOR)

    supervisor.tick()
    assert agents_for(parent_task) == [parent]

    del supervisor.live[parent]
    supervisor.tick()
    assert len(agents_for(parent_task)) == 2


def test_startup_resolves_stale_rows_by_checking_the_pid(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    spoke = bus.enqueue(tmp_path / "spoke", parent_agent=HUMAN)
    alive = bus.enqueue(tmp_path / "alive", parent_agent=HUMAN)
    dead = bus.enqueue(tmp_path / "dead", parent_agent=HUMAN)
    never = bus.enqueue(tmp_path / "never", parent_agent=HUMAN)

    _write_completed(tmp_path / "spoke")
    for agent, pid in ((spoke, 101), (alive, 102), (dead, 103)):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(never, AgentStatus.CLAIMED, EventSource.SUPERVISOR)

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=1_000_000,
        poll_s=1.0,
        clock=bus.clock,
        liveness=FakeLiveness(frozenset({102})),
    ).resolve_stale()

    assert bus.attempt(spoke) == Closed(verdict=AgentStatus.COMPLETED)
    assert bus.state(alive).status is AgentStatus.RUNNING
    assert bus.state(dead).status is AgentStatus.CRASHED
    assert bus.state(never).status is AgentStatus.CRASHED


def test_startup_kills_a_wedged_agent_past_the_timeout_and_leaves_a_fresh_one_running(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    wedged = bus.enqueue(tmp_path / "wedged", parent_agent=HUMAN)
    fresh = bus.enqueue(tmp_path / "fresh", parent_agent=HUMAN)

    bus.record(wedged, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(wedged, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=301)
    bus.clock.sleep(10)
    bus.record(fresh, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(fresh, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=302)
    bus.clock.sleep(1)

    liveness = FakeLiveness(frozenset({301, 302}))
    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=bus.clock,
        liveness=liveness,
    ).resolve_stale()

    assert bus.state(wedged).status is AgentStatus.TIMED_OUT
    assert bus.state(fresh).status is AgentStatus.RUNNING
    assert liveness.killed == [301]


def test_a_startup_kill_leaves_a_close_that_collect_task_can_report(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    migrate_file(run_dir / "bus.db", latest_version())
    clock = FakeClock()
    bus = Bus.open(run_dir / "bus.db", clock)
    ctx = _ctx(tmp_path)
    role = Role(behaviour="b", tools=(), budget=Budget(turns=20, tool_calls=60))
    delegate = DelegateTo("worker", role, run_dir, parent=HUMAN, clock=clock)
    args = delegate.args_model(task_id="wedged", goal="g", input=FreeText(text="go"))
    assert delegate.run(args, ctx).ok is True
    child = bus.active_for(run_dir / "tasks" / "wedged")[0].agent

    bus.record(child, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(child, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=401)
    clock.sleep(10)

    Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=5,
        poll_s=1.0,
        clock=clock,
        liveness=FakeLiveness(frozenset({401})),
    ).resolve_stale()

    assert bus.attempt(child) == Lost(close=AgentStatus.TIMED_OUT)
    assert (run_dir / "tasks" / "wedged" / "outcome.json").exists() is False

    collected = CollectTask(run_dir=run_dir, clock=clock).run(TaskArgs(task=child), ctx)

    assert collected.ok is False
    assert collected.error == f"agent {child} ended as timed_out: killed after 5s at startup"
    assert AgentStatus.COLLECTED in [e.status for e in bus.history(child)]


def test_a_healthy_worker_left_by_a_previous_supervisor_is_adopted_and_reaped(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    task_dir = tmp_path / "adopted"
    task_dir.mkdir()
    agent = bus.enqueue(task_dir, parent_agent=HUMAN)
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)

    first = Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=600,
        clock=bus.clock,
        liveness=FakeLiveness(alive=frozenset({4242})),
    )
    first.resolve_stale()
    assert bus.attempt(agent) == Running(pid=4242)
    assert agent in first.live

    (task_dir / "outcome.json").write_text(
        Completed[FreeText](
            value=FreeText(text="done"), summary="done", spent=Budget(turns=1, tool_calls=1)
        ).model_dump_json()
    )

    second = Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=600,
        clock=bus.clock,
        liveness=FakeLiveness(alive=frozenset()),
    )
    second.resolve_stale()
    assert bus.attempt(agent) == Closed(verdict=AgentStatus.COMPLETED)

    nearly_wedged_dir = tmp_path / "nearly-wedged"
    nearly_wedged_dir.mkdir()
    nearly_wedged = bus.enqueue(nearly_wedged_dir, parent_agent=HUMAN)
    bus.record(nearly_wedged, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(nearly_wedged, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=5353)

    bus.clock.sleep(590)
    third = Supervisor(
        bus=bus,
        spawner=FakeSpawner([]),
        max_concurrent=2,
        timeout_s=600,
        clock=bus.clock,
        liveness=FakeLiveness(alive=frozenset({5353})),
    )
    third.resolve_stale()
    assert nearly_wedged in third.live

    bus.clock.sleep(11)
    third.tick()
    assert bus.attempt(nearly_wedged) == Lost(close=AgentStatus.TIMED_OUT)
