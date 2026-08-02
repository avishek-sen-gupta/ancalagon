import typing


class Process(typing.Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def kill(self) -> None: ...
