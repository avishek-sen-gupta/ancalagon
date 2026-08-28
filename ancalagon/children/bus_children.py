# A session's children as the bus sees them, for the agent that owns them.
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.children.children import Children
from ancalagon.schedule.live_children import live_children
from ancalagon.schedule.uncollected import uncollected


class BusChildren(Children):
    def __init__(self, bus: LifecycleStore, agent: int):
        self.bus = bus
        self.agent = agent

    def outstanding(self) -> tuple[int, ...]:
        snapshot = self.bus.snapshot()
        return live_children(snapshot, self.agent)

    def uncollected(self) -> tuple[int, ...]:
        snapshot = self.bus.snapshot()
        return uncollected(snapshot, snapshot.task_by_agent[self.agent])

    def seen_through(self) -> int:
        snapshot = self.bus.snapshot()
        return max((e.id for events in snapshot.events.values() for e in events), default=0)
