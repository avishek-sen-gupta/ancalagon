# The real clock, used everywhere outside tests.
import datetime
import time

from ancalagon.clock.clock import Clock


class SystemClock(Clock):
    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.UTC)

    def time(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
