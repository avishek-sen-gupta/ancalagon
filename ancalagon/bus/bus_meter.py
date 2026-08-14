# A Meter that writes each call to the run's database.
from ancalagon.bus.bus import Bus
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.llm.meter import Meter


class BusMeter(Meter):
    def __init__(self, bus: Bus):
        self.bus = bus

    def record(self, agent: int, usage: CallUsage) -> None:
        self.bus.record_call(agent, usage)
