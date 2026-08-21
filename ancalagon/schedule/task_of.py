# The task an agent belongs to.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.harness_task import HarnessTask


def task_of(snapshot: Snapshot, agent: int) -> HarnessTask:
    task = snapshot.task_by_agent[agent]
    return next(t for t in snapshot.tasks if t.id == task)
