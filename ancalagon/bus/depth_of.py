# Counts an agent's ancestors, with the root at zero, so max_depth can bound nesting.
from ancalagon.bus.bus import Bus

MAX_HOPS = 64


def depth_of(bus: Bus, agent: int) -> int:
    depth = 0
    current = bus.state(agent).parent_agent
    while current != 0:
        if depth >= MAX_HOPS:
            raise ValueError(f"agent {agent} exceeds {MAX_HOPS} ancestors; parent chain is cyclic")
        current = bus.state(current).parent_agent
        depth += 1
    return depth
