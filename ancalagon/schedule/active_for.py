# Every agent at a directory whose attempt is still queued, claimed or running.
from ancalagon.attempt.claimed import Claimed
from ancalagon.attempt.queued import Queued
from ancalagon.attempt.running import Running
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.schedule.task_of import task_of


def active_for(snapshot: Snapshot, dir: str) -> tuple[int, ...]:
    return tuple(
        agent
        for agent, attempt in snapshot.attempts.items()
        if task_of(snapshot, agent).dir == dir and isinstance(attempt, (Queued, Claimed, Running))
    )
