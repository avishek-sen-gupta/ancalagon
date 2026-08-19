# Asks the operating system whether a pid exists, which is all it can tell us.
import os

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


OS_LIVENESS = OsLiveness()
