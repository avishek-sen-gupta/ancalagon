# The most recent thing recorded about an agent. Events are appended, so the last is the latest.
import operator

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_event import AgentEvent

BY_ID = operator.attrgetter("id")


def latest_event(snapshot: Snapshot, agent: int) -> AgentEvent:
    return max(snapshot.events[agent], key=BY_ID)
