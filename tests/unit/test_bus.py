import pathlib

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import Bus
from ancalagon.bus.depth_of import depth_of
from ancalagon.bus.event_source import EventSource


def test_bus_appends_agent_history_and_claims_each_agent_once(tmp_path: pathlib.Path):
    db = tmp_path / "bus.db"
    bus = Bus.create(db)
    other = Bus.open(db)
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

    assert [(e.status.value, e.source.value) for e in bus.history(first)] == [
        ("queued", "supervisor"),
        ("claimed", "supervisor"),
        ("running", "supervisor"),
        ("needs_input", "worker"),
        ("exited", "supervisor"),
    ]
    assert [s.agent for s in bus.live()] == [second]
    assert bus.active_for(alpha) == []

    retried = bus.enqueue(alpha, parent_agent=0)
    assert retried != first
    assert bus.task(alpha).id == bus.state(first).task == bus.state(retried).task
    assert [s.agent for s in bus.active_for(alpha)] == [retried]

    bus.post(sender=first, addressee=0, kind="task_done", summary="done", ref_path=str(alpha))
    inbox = bus.inbox(consumer=0)
    assert [m.kind for m in inbox] == ["task_done"]
    assert inbox[0].sender == first
    assert bus.inbox(consumer=0) == []


def test_depth_counts_ancestors_with_the_root_at_zero(tmp_path: pathlib.Path):
    bus = Bus.create(tmp_path / "bus.db")
    root = bus.enqueue(tmp_path / "tasks" / "root", parent_agent=0)
    child = bus.enqueue(tmp_path / "tasks" / "child", parent_agent=root)
    grandchild = bus.enqueue(tmp_path / "tasks" / "grandchild", parent_agent=child)

    assert depth_of(bus, root) == 0
    assert depth_of(bus, child) == 1
    assert depth_of(bus, grandchild) == 2
