from ancalagon.bus.bus import Bus

MAX_HOPS = 64


def depth_of(bus: Bus, task_id: int) -> int:
    depth = 0
    current = bus.get(task_id).parent
    while current != 0:
        if depth >= MAX_HOPS:
            raise ValueError(f"task {task_id} exceeds {MAX_HOPS} ancestors; parent chain is cyclic")
        current = bus.get(current).parent
        depth += 1
    return depth
