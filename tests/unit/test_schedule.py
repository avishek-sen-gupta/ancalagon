# The scheduling rules, exercised as pure functions of a snapshot.
from collections.abc import Mapping, Sequence

from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.harness_task import HarnessTask
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.depth_of import depth_of
from ancalagon.schedule.has_news import has_news
from ancalagon.schedule.is_news import is_news
from ancalagon.schedule.live_children import live_children
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.schedule.outstanding import outstanding
from ancalagon.schedule.task_of import task_of
from ancalagon.schedule.uncollected import uncollected
from ancalagon.schedule.unreaped import unreaped
from ancalagon.schedule.wakeable import wakeable


def _snapshot(
    tasks: Sequence[tuple[int, str, int]],
    agents: Sequence[tuple[int, int]],
    events: Mapping[int, Sequence[tuple[int, AgentStatus, EventSource]]],
) -> Snapshot:
    built = {
        agent: tuple(
            AgentEvent(id=i, agent=agent, ts="t", status=s, source=src, pid=0, summary="")
            for i, s, src in rows
        )
        for agent, rows in events.items()
    }
    return Snapshot(
        tasks=tuple(HarnessTask(id=i, dir=d, parent_agent=p, created="t") for i, d, p in tasks),
        agents_by_task={t: tuple(a for a, owner in agents if owner == t) for t, _, _ in tasks},
        task_by_agent={a: t for a, t in agents},
        events=built,
        attempts={agent: attempt_of(found) for agent, found in built.items()},
    )


def test_the_scheduling_rules_read_a_snapshot():
    S = EventSource.SUPERVISOR
    snap = _snapshot(
        tasks=[(1, "/root", 0), (2, "/child", 1)],
        agents=[(1, 1), (2, 2)],
        events={
            1: [
                (1, AgentStatus.QUEUED, S),
                (2, AgentStatus.CLAIMED, S),
                (3, AgentStatus.RUNNING, S),
                (4, AgentStatus.IDLING, S),
            ],
            2: [
                (5, AgentStatus.QUEUED, S),
                (6, AgentStatus.CLAIMED, S),
                (7, AgentStatus.RUNNING, S),
                (8, AgentStatus.COMPLETED, S),
            ],
        },
    )

    assert newest_agent(snap, 1) == 1
    assert task_of(snap, 2).dir == "/child"
    assert outstanding(snap, 1) is True
    assert outstanding(snap, 2) is False
    assert uncollected(snap, 1) == (2,)
    assert live_children(snap, 1) == ()
    assert active_for(snap, "/child") == ()
    assert unreaped(snap) == ()
    assert is_news(snap, 1) is False
    assert is_news(snap, 2) is True
    assert has_news(snap, 1) is True
    assert [t.dir for t in wakeable(snap)] == ["/root"]
    assert depth_of(snap, 2) == 1
