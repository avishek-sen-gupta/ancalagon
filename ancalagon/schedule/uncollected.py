# A task's children whose newest agent has closed or been lost, but not yet collected.
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.schedule.newest_agent import newest_agent


def uncollected(snapshot: Snapshot, task: int) -> tuple[int, ...]:
    return tuple(
        newest_agent(snapshot, t.id)
        for t in snapshot.tasks
        if t.parent_agent in snapshot.agents_by_task[task]
        and isinstance(snapshot.attempts[newest_agent(snapshot, t.id)], (Closed, Lost))
    )
