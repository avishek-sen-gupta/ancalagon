# Whether a task's child has settled with something its parent had not seen when it idled.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.schedule.is_news import is_news
from ancalagon.schedule.newest_agent import newest_agent


def has_news(snapshot: Snapshot, task: int) -> bool:
    parent = newest_agent(snapshot, task)
    match [e for e in snapshot.events[parent] if e.status is AgentStatus.IDLING]:
        case [idled]:
            return any(
                is_news(snapshot, newest_agent(snapshot, child.id))
                and max(e.id for e in snapshot.events[newest_agent(snapshot, child.id)])
                > idled.seen_through
                for child in snapshot.tasks
                if child.parent_agent in snapshot.agents_by_task[task]
            )
        case _:
            return False
