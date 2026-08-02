import typing


class Clock(typing.Protocol):
    def time(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...
