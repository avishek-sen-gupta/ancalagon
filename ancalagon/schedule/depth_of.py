# Counts an agent's ancestors, with the root at zero, so max_depth can bound nesting.
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.schedule.task_of import task_of

MAX_HOPS = 64


def _depth_from(snapshot: Snapshot, agent: int, current: int, depth: int) -> int:
    if current == 0:
        return depth
    if depth >= MAX_HOPS:
        raise ValueError(f"agent {agent} exceeds {MAX_HOPS} ancestors; parent chain is cyclic")
    return _depth_from(snapshot, agent, task_of(snapshot, current).parent_agent, depth + 1)


def depth_of(snapshot: Snapshot, agent: int) -> int:
    return _depth_from(snapshot, agent, task_of(snapshot, agent).parent_agent, 0)
