# Injected time, so timestamps are deterministic and timeouts need no waiting.
import datetime
import typing


class Clock(typing.Protocol):
    def now(self) -> datetime.datetime: ...

    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...
