# Every agent, across all tasks, still claimed or running.
from ancalagon.attempt.claimed import Claimed
from ancalagon.attempt.running import Running
from ancalagon.attempt.snapshot import Snapshot


def unreaped(snapshot: Snapshot) -> tuple[int, ...]:
    return tuple(
        agent
        for agent, attempt in snapshot.attempts.items()
        if isinstance(attempt, (Claimed, Running))
    )
