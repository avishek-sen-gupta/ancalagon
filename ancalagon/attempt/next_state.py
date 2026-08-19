# The single transition table: the one legal next state for an event, or a rejection.
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
from ancalagon.attempt.illegal_transition import IllegalTransition
from ancalagon.attempt.nascent import Nascent
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource

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


def next_state(state: Attempt, event: AgentEvent) -> Attempt:
    match (state, event.status, event.source):
        case (Nascent(), AgentStatus.QUEUED, EventSource.SUPERVISOR):
            return Queued()
        case (_, AgentStatus.CLAIMED, EventSource.SUPERVISOR):
            return Claimed()
        case (Claimed(), AgentStatus.RUNNING, EventSource.SUPERVISOR):
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
            raise IllegalTransition(
                f"cannot record {event.status.value!r} from {event.source.value!r} " f"on {state!r}"
            )
