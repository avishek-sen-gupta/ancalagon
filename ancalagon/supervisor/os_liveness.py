# Asks the operating system whether a pid exists, or kills one, which is all it can tell or do.
import os
import signal

from ancalagon.supervisor.liveness import Liveness


class OsLiveness(Liveness):
    def is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def kill(self, pid: int) -> None:
        os.kill(pid, signal.SIGKILL)


OS_LIVENESS = OsLiveness()
