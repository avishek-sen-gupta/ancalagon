# The real clock, used everywhere outside tests.
import time
from ancalagon.supervisor.clock import Clock


class SystemClock(Clock):
    def time(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
