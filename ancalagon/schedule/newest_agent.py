# The most recently created agent attempting a task.
from ancalagon.attempt.snapshot import Snapshot


def newest_agent(snapshot: Snapshot, task: int) -> int:
    return snapshot.agents_by_task[task][-1]
