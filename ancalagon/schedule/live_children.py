# The newest agents of a task's children whose work is still outstanding.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.schedule.outstanding import outstanding
from ancalagon.schedule.task_of import task_of


def live_children(snapshot: Snapshot, agent: int) -> tuple[int, ...]:
    task = task_of(snapshot, agent).id
    return tuple(
        newest_agent(snapshot, t.id)
        for t in snapshot.tasks
        if t.parent_agent in snapshot.agents_by_task[task] and outstanding(snapshot, t.id)
    )
