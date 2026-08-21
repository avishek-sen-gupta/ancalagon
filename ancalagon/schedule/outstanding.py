# Whether a task still has work in flight, counting an idled parent as outstanding.
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.collected import Collected
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.schedule.newest_agent import newest_agent


def outstanding(snapshot: Snapshot, task: int) -> bool:
    match snapshot.attempts[newest_agent(snapshot, task)]:
        case Closed(verdict=closed_verdict):
            return closed_verdict is AgentStatus.IDLING
        case Collected(verdict=collected_verdict):
            return collected_verdict is AgentStatus.IDLING
        case Lost():
            return False
        case _:
            return True
