# A meter that counts nothing, for callers who do not want the accounting.
from ancalagon.contracts.call_usage import CallUsage


class Unmetered:
    def record(self, agent: int, usage: CallUsage) -> None:
        return None
