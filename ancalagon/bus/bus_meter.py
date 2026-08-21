# A Meter that writes each call to the run's database.
from ancalagon.bus.meter_store import MeterStore
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.llm.meter import Meter


class BusMeter(Meter):
    def __init__(self, meter_store: MeterStore):
        self.meter_store = meter_store

    def record(self, agent: int, usage: CallUsage) -> None:
        self.meter_store.record_call(agent, usage)
