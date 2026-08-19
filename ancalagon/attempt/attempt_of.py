# Folds an attempt's events into the single state they describe.
import functools
from collections.abc import Sequence

from ancalagon.attempt.attempt import (
    Attempt,
    Claimed,
    Closed,
    Collected,
    Lost,
    Queued,
    Reported,
    Running,
)
from ancalagon.bus.agent_event import AgentEvent
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.event_source import EventSource

VERDICTS = frozenset(
    {
        AgentStatus.COMPLETED,
        AgentStatus.EXHAUSTED,
        AgentStatus.FAILED,
        AgentStatus.NEEDS_INPUT,
        AgentStatus.IDLING,
    }
)
CLOSES = frozenset({AgentStatus.EXITED, AgentStatus.CRASHED, AgentStatus.TIMED_OUT})


def _step(state: Attempt, event: AgentEvent) -> Attempt:
    match (state, event.status, event.source):
        case (_, AgentStatus.QUEUED, EventSource.SUPERVISOR):
            return Queued()
        case (_, AgentStatus.CLAIMED, EventSource.SUPERVISOR):
            return Claimed()
        case (_, AgentStatus.RUNNING, EventSource.SUPERVISOR):
            return Running(pid=event.pid)
        case (Running(), worker_status, EventSource.WORKER) if worker_status in VERDICTS:
            return Reported(verdict=worker_status)
        case (Reported(verdict=reported_verdict), close_status, EventSource.SUPERVISOR) if (
            close_status in CLOSES
        ):
            return Closed(verdict=reported_verdict)
        case (_, unspoken_close, EventSource.SUPERVISOR) if unspoken_close in CLOSES:
            return Lost(close=unspoken_close)
        case (Closed(verdict=closed_verdict), AgentStatus.COLLECTED, EventSource.WORKER):
            return Collected(verdict=closed_verdict, spoke=True)
        case (Lost(close=lost_close), AgentStatus.COLLECTED, EventSource.WORKER):
            return Collected(verdict=lost_close, spoke=False)
        case _:
            raise ValueError(
                f"no transition for {state!r} on {event.status!r} from {event.source!r}"
            )


def attempt_of(events: Sequence[AgentEvent]) -> Attempt:
    return functools.reduce(_step, events, Queued())
