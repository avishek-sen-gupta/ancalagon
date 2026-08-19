# A Liveness that answers from a fixed set, so a test can decide who is running.
from ancalagon.liveness.liveness import Liveness


class FakeLiveness(Liveness):
    def __init__(self, alive: frozenset[int]):
        self.alive = alive

    def is_running(self, pid: int) -> bool:
        return pid in self.alive
