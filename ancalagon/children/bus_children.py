# A session's children as the bus sees them, for the agent that owns them.
from ancalagon.bus.bus import Bus
from ancalagon.children.children import Children


class BusChildren(Children):
    def __init__(self, bus: Bus, agent: int):
        self.bus = bus
        self.agent = agent

    def outstanding(self) -> tuple[int, ...]:
        return tuple(s.agent for s in self.bus.live_children(self.agent))

    def uncollected(self) -> tuple[int, ...]:
        return tuple(self.bus.uncollected(self.bus.state(self.agent).task))
