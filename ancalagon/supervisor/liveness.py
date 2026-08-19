# Whether a process this supervisor does not own is still running.
import typing


class Liveness(typing.Protocol):
    def is_running(self, pid: int) -> bool: ...
