# Injected time, so timeout behaviour can be tested without waiting.
import typing


class Clock(typing.Protocol):
    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...
