# Whether a process this supervisor does not own is still running, or should be stopped.
import typing


class Liveness(typing.Protocol):
    def is_running(self, pid: int) -> bool: ...

    def kill(self, pid: int) -> None: ...
