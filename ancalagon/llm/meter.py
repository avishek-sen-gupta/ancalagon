# Where a session reports what each model call consumed.
import typing

from ancalagon.contracts.call_usage import CallUsage


class Meter(typing.Protocol):
    def record(self, agent: int, usage: CallUsage) -> None: ...
