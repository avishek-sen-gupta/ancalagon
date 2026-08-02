from ancalagon.bus.bus import Bus


def depth_of(bus: Bus, task_id: int) -> int:
    depth = 0
    current = task_id
    while current != 0:
        current = bus.get(current).parent
        depth += 1
    return depth
