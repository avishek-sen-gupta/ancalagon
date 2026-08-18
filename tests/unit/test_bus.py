import pathlib

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import HUMAN, Bus
from ancalagon.bus.depth_of import depth_of
from ancalagon.bus.event_source import EventSource
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.migrations import latest_version, migrate_file


def _open(tmp_path: pathlib.Path) -> Bus:
    db = tmp_path / "bus.db"
    migrate_file(db, latest_version())
    return Bus.open(db, FakeClock())


def test_bus_appends_agent_history_and_claims_each_agent_once(tmp_path: pathlib.Path):
    db = tmp_path / "bus.db"
    migrate_file(db, latest_version())
    clock = FakeClock()
    bus = Bus.open(db, clock)
    other = Bus.open(db, SystemClock())
    alpha = tmp_path / "tasks" / "alpha"

    first = bus.enqueue(alpha, parent_agent=0)
    second = bus.enqueue(tmp_path / "tasks" / "beta", parent_agent=first)
    assert bus.state(first).status is AgentStatus.QUEUED
    assert bus.state(second).parent_agent == first

    claimed = bus.claim(limit=10)
    assert sorted(s.agent for s in claimed) == [first, second]
    assert other.claim(limit=10) == []
    assert bus.state(first).status is AgentStatus.CLAIMED

    bus.record(first, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=4242)
    assert bus.state(first).pid == 4242
    assert [s.agent for s in bus.live()] == [first, second]

    bus.record(first, AgentStatus.NEEDS_INPUT, EventSource.WORKER, summary="which caption?")
    bus.record(first, AgentStatus.EXITED, EventSource.SUPERVISOR, exit_code=0)

    assert [e.ts for e in bus.history(first)] == ["2026-01-01T00:00:00+00:00"] * 5

    assert [(e.status.value, e.source.value) for e in bus.history(first)] == [
        ("queued", "supervisor"),
        ("claimed", "supervisor"),
        ("running", "supervisor"),
        ("needs_input", "worker"),
        ("exited", "supervisor"),
    ]
    assert [s.agent for s in bus.live()] == [second]
    assert bus.active_for(alpha) == []

    clock.sleep(90)
    retried = bus.enqueue(alpha, parent_agent=0)
    assert retried != first
    assert bus.history(retried)[0].ts == "2026-01-01T00:01:30+00:00"
    assert bus.task(alpha).id == bus.state(first).task == bus.state(retried).task
    assert [s.agent for s in bus.active_for(alpha)] == [retried]


def test_depth_counts_ancestors_with_the_root_at_zero(tmp_path: pathlib.Path):
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = Bus.open(tmp_path / "bus.db", SystemClock())
    root = bus.enqueue(tmp_path / "tasks" / "root", parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=root)
    grandchild = bus.enqueue(tmp_path / "tasks" / "grandchild", parent_agent=child)

    assert depth_of(bus, root) == 0
    assert depth_of(bus, child) == 1
    assert depth_of(bus, grandchild) == 2


def test_the_bus_knows_which_children_are_live_and_which_parents_may_resume(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    first = bus.enqueue(tmp_path / "a", parent_agent=parent)
    second = bus.enqueue(tmp_path / "b", parent_agent=parent)

    assert [s.agent for s in bus.live_children(parent)] == [first, second]
    assert bus.resumable_idle(parent) is False

    bus.record(parent, AgentStatus.IDLING, EventSource.WORKER)
    bus.record(parent, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert bus.resumable_idle(parent) is True

    bus.record(first, AgentStatus.COMPLETED, EventSource.WORKER)
    bus.record(first, AgentStatus.EXITED, EventSource.SUPERVISOR)
    assert [s.agent for s in bus.live_children(parent)] == [second]

    resumed = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    assert resumed != parent
    assert bus.resumable_idle(resumed) is False
    assert bus.resumable_idle(parent) is False
