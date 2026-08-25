# The agent a task is addressed by now, given any agent that ever served it.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.schedule.newest_agent import newest_agent


def addressed(snapshot: Snapshot, agent: int) -> int:
    return newest_agent(snapshot, snapshot.task_by_agent[agent])
