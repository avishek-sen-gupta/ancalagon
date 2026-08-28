# Where a session learns which of its children are still working and which have not been read.
import typing


class Children(typing.Protocol):
    def outstanding(self) -> tuple[int, ...]: ...

    def uncollected(self) -> tuple[int, ...]: ...
