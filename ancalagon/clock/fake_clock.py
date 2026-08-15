# A clock that only moves when told to, so timestamps and timeouts are exact in tests.
import datetime

from ancalagon.clock.clock import Clock

EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class FakeClock(Clock):
    def __init__(self) -> None:
        self.elapsed = 0.0

    def now(self) -> datetime.datetime:
        return EPOCH + datetime.timedelta(seconds=self.elapsed)

    def time(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds
