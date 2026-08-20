import pathlib
import sqlite3

import pytest

from ancalagon.attempt.claimed import Claimed
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.illegal_transition import IllegalTransition
from ancalagon.attempt.running import Running
from ancalagon.bus.bus import HUMAN, Bus
from ancalagon.bus.depth_of import depth_of
from ancalagon.children.bus_children import BusChildren
from ancalagon.children.no_children import NO_CHILDREN
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.migrations import latest_version, migrate_file
from tests.unit.conftest import settle


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
    assert bus.attempt(first) == Running(pid=4242)
    assert bus.attempt(second) == Claimed()

    bus.record(first, AgentStatus.NEEDS_INPUT, EventSource.SUPERVISOR, summary="which caption?")

    assert [e.ts for e in bus.history(first)] == ["2026-01-01T00:00:00+00:00"] * 4

    assert [(e.status.value, e.source.value) for e in bus.history(first)] == [
        ("queued", "supervisor"),
        ("claimed", "supervisor"),
        ("running", "supervisor"),
        ("needs_input", "supervisor"),
    ]
    assert bus.attempt(first) == Closed(verdict=AgentStatus.NEEDS_INPUT)
    assert bus.attempt(second) == Claimed()
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


def test_the_bus_knows_which_children_are_live(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    first = bus.enqueue(tmp_path / "a", parent_agent=parent)
    second = bus.enqueue(tmp_path / "b", parent_agent=parent)

    assert [s.agent for s in bus.live_children(parent)] == [first, second]

    settle(bus, parent, AgentStatus.IDLING)

    settle(bus, first, AgentStatus.COMPLETED)
    assert [s.agent for s in bus.live_children(parent)] == [second]


def test_a_task_sees_children_from_every_attempt_and_knows_when_it_is_outstanding(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    first = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    early = bus.enqueue(tmp_path / "early", parent_agent=first)

    assert [s.agent for s in bus.live_children(first)] == [early]
    assert bus.outstanding(bus.state(early).task) is True

    settle(bus, first, AgentStatus.IDLING)
    woken = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    late = bus.enqueue(tmp_path / "late", parent_agent=woken)

    assert sorted(s.agent for s in bus.live_children(woken)) == [early, late]

    settle(bus, early, AgentStatus.COMPLETED)
    assert [s.agent for s in bus.live_children(woken)] == [late]
    assert bus.outstanding(bus.state(early).task) is False

    settle(bus, late, AgentStatus.IDLING, pid=2)
    assert bus.outstanding(bus.state(late).task) is True
    assert [s.agent for s in bus.live_children(woken)] == [late]


def test_a_task_is_wakeable_only_for_news_a_supervisor_has_marked(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    first = bus.enqueue(tmp_path / "a", parent_agent=parent)
    second = bus.enqueue(tmp_path / "b", parent_agent=parent)

    assert bus.wakeable() == []

    settle(bus, parent, AgentStatus.IDLING)
    assert bus.wakeable() == []

    bus.record(first, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(first, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    assert bus.wakeable() == []
    bus.record(first, AgentStatus.COMPLETED, EventSource.SUPERVISOR)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]

    woken = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    assert bus.wakeable() == []

    settle(bus, woken, AgentStatus.IDLING)
    assert bus.wakeable() == []

    bus.record(second, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(second, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)
    assert bus.wakeable() == []
    bus.record(second, AgentStatus.CRASHED, EventSource.SUPERVISOR)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]

    rewoken = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    idled_child = bus.enqueue(tmp_path / "c", parent_agent=rewoken)
    reporting_child = bus.enqueue(tmp_path / "d", parent_agent=rewoken)
    assert bus.wakeable() == []

    settle(bus, rewoken, AgentStatus.IDLING)
    assert bus.wakeable() == []

    settle(bus, idled_child, AgentStatus.IDLING, pid=3)
    assert bus.wakeable() == []

    settle(bus, reporting_child, AgentStatus.COMPLETED, pid=4)
    assert [t.dir for t in bus.wakeable()] == [str(tmp_path / "root")]


def test_children_reports_outstanding_and_uncollected_for_one_agent(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    bus.enqueue(tmp_path / "warmup", parent_agent=HUMAN)
    bus.enqueue(tmp_path / "warmup", parent_agent=HUMAN)
    parent = bus.enqueue(tmp_path / "root", parent_agent=HUMAN)
    done = bus.enqueue(tmp_path / "done", parent_agent=parent)
    busy = bus.enqueue(tmp_path / "busy", parent_agent=parent)
    assert bus.state(parent).task != parent

    children = BusChildren(bus, parent)
    assert children.outstanding() == (done, busy)
    assert children.uncollected() == ()

    settle(bus, done, AgentStatus.COMPLETED)
    assert children.outstanding() == (busy,)
    assert children.uncollected() == (done,)

    bus.record(done, AgentStatus.COLLECTED, EventSource.WORKER)
    assert children.uncollected() == ()

    assert NO_CHILDREN.outstanding() == ()
    assert NO_CHILDREN.uncollected() == ()


def test_record_refuses_a_transition_the_lifecycle_does_not_allow(tmp_path: pathlib.Path):
    bus = _open(tmp_path)
    agent = bus.enqueue(tmp_path / "a", parent_agent=HUMAN)

    with pytest.raises(IllegalTransition, match="collected"):
        bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)
    with pytest.raises(IllegalTransition, match="running"):
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    with pytest.raises(IllegalTransition, match="queued"):
        bus.record(agent, AgentStatus.QUEUED, EventSource.SUPERVISOR)

    settle(bus, agent, AgentStatus.COMPLETED)
    bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)

    with pytest.raises(IllegalTransition, match="collected"):
        bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)
    with pytest.raises(IllegalTransition, match="running"):
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)
    with pytest.raises(IllegalTransition, match="claimed"):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    with pytest.raises(IllegalTransition, match="timed_out"):
        bus.record(agent, AgentStatus.TIMED_OUT, EventSource.SUPERVISOR)

    closed = bus.enqueue(tmp_path / "b", parent_agent=HUMAN)
    settle(bus, closed, AgentStatus.COMPLETED)
    with pytest.raises(IllegalTransition, match="crashed"):
        bus.record(closed, AgentStatus.CRASHED, EventSource.SUPERVISOR)


def test_a_rejected_record_leaves_no_open_transaction_and_no_partial_write(
    tmp_path: pathlib.Path,
):
    bus = _open(tmp_path)
    agent = bus.enqueue(tmp_path / "a", parent_agent=HUMAN)
    before = bus.history(agent)

    with pytest.raises(IllegalTransition):
        bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)

    assert bus.conn.in_transaction is False
    assert bus.history(agent) == before

    bus.conn.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError):
        bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    assert bus.history(agent) == before
    bus.conn.execute("ROLLBACK")
