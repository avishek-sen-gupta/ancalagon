# The slice of subprocess.Popen the supervisor uses, so tests can substitute a fake.
import typing


class Process(typing.Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def kill(self) -> None: ...
