# Where a run says what it is doing, for anyone watching without knowing its directory.
import typing

from ancalagon.contracts.line import Line


class Sink(typing.Protocol):
    def publish(self, line: Line) -> None: ...
