# A worker this supervisor did not spawn, watched through Liveness because it has no pipe.
from ancalagon.supervisor.liveness import Liveness

ENDED = -1


class AdoptedProcess:
    def __init__(self, pid: int, liveness: Liveness):
        self.pid = pid
        self.liveness = liveness

    def poll(self):
        return None if self.liveness.is_running(self.pid) else ENDED

    def kill(self) -> None:
        self.liveness.kill(self.pid)
