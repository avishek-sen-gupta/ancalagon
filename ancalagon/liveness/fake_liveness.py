# A Liveness that answers from a fixed set and records kills, so a test can watch without mocking.
from ancalagon.liveness.liveness import Liveness


class FakeLiveness(Liveness):
    def __init__(self, alive: frozenset[int]):
        self.alive = alive
        self.killed: list[int] = []

    def is_running(self, pid: int) -> bool:
        return pid in self.alive

    def kill(self, pid: int) -> None:
        self.killed = [*self.killed, pid]
