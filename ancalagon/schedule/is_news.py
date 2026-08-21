# Whether an agent's attempt settled with something a parent hasn't seen yet.
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_status import AgentStatus


def is_news(snapshot: Snapshot, agent: int) -> bool:
    match snapshot.attempts[agent]:
        case Closed(verdict=verdict):
            return verdict is not AgentStatus.IDLING
        case Lost():
            return True
        case _:
            return False
