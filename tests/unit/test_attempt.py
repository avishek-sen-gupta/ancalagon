from ancalagon.attempt.attempt import (
    Claimed,
    Closed,
    Collected,
    Lost,
    Queued,
    Running,
)
from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.nascent import Nascent
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource


def _events(*pairs: tuple[AgentStatus, EventSource]) -> list[AgentEvent]:
    return [
        AgentEvent(id=i, agent=1, ts="t", status=s, source=src, pid=0, summary="")
        for i, (s, src) in enumerate(pairs, start=1)
    ]


def test_every_lifecycle_path_folds_to_the_state_it_describes():
    W, S = EventSource.WORKER, EventSource.SUPERVISOR

    assert attempt_of([]) == Nascent()

    assert attempt_of(_events((AgentStatus.QUEUED, S))) == Queued()
    assert attempt_of(_events((AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S))) == Claimed()
    assert attempt_of(
        _events((AgentStatus.QUEUED, S), (AgentStatus.CLAIMED, S), (AgentStatus.CRASHED, S))
    ) == Lost(close=AgentStatus.CRASHED)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S),
            (AgentStatus.CLAIMED, S),
            (AgentStatus.RUNNING, S),
            (AgentStatus.FAILED, S),
        )
    ) == Closed(verdict=AgentStatus.FAILED)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S),
            (AgentStatus.CLAIMED, S),
            (AgentStatus.RUNNING, S),
            (AgentStatus.TIMED_OUT, S),
        )
    ) == Lost(close=AgentStatus.TIMED_OUT)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S),
            (AgentStatus.CLAIMED, S),
            (AgentStatus.RUNNING, S),
            (AgentStatus.COMPLETED, S),
            (AgentStatus.COLLECTED, W),
        )
    ) == Collected(verdict=AgentStatus.COMPLETED, spoke=True)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S),
            (AgentStatus.CLAIMED, S),
            (AgentStatus.RUNNING, S),
            (AgentStatus.CRASHED, S),
            (AgentStatus.COLLECTED, W),
        )
    ) == Collected(verdict=AgentStatus.CRASHED, spoke=False)
    assert attempt_of(
        _events(
            (AgentStatus.QUEUED, S),
            (AgentStatus.CLAIMED, S),
            (AgentStatus.RUNNING, S),
            (AgentStatus.COMPLETED, S),
        )
    ) == Closed(verdict=AgentStatus.COMPLETED)


def test_running_carries_the_spawned_pid():
    S = EventSource.SUPERVISOR
    events = [
        AgentEvent(
            id=1,
            agent=1,
            ts="t",
            status=AgentStatus.QUEUED,
            source=S,
            pid=0,
            summary="",
        ),
        AgentEvent(
            id=2,
            agent=1,
            ts="t",
            status=AgentStatus.CLAIMED,
            source=S,
            pid=0,
            summary="",
        ),
        AgentEvent(
            id=3,
            agent=1,
            ts="t",
            status=AgentStatus.RUNNING,
            source=S,
            pid=4242,
            summary="",
        ),
    ]
    assert attempt_of(events) == Running(pid=4242)
