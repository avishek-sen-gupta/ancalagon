# The real clock, used everywhere outside tests.
import time


class SystemClock:
    def time(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
