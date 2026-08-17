# A meter that counts nothing, for callers who do not want the accounting.
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.llm.meter import Meter


class Unmetered(Meter):
    def record(self, agent: int, usage: CallUsage) -> None:
        return None


UNMETERED = Unmetered()
