import logging
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.bus.task_status import TaskStatus
from ancalagon.supervisor.clock import Clock
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner
from ancalagon.supervisor.system_clock import SystemClock

LOGGER = logging.getLogger(__name__)


class Supervisor:
    def __init__(
        self,
        bus: Bus,
        spawner: Spawner,
        max_concurrent: int,
        timeout_s: int,
        poll_s: float = 0.05,
        clock: Clock = SystemClock(),
    ):
        self.bus = bus
        self.spawner = spawner
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.live: dict[int, Process] = {}
        self.started: dict[int, float] = {}

    def _start_queued(self) -> None:
        free = self.max_concurrent - len(self.live)
        if free <= 0:
            return
        for row in self.bus.claim(limit=free):
            process = self.spawner.spawn(pathlib.Path(row.dir), row.id)
            self.bus.mark_running(row.id, pid=process.pid)
            self.live[row.id] = process
            self.started[row.id] = self.clock.time()

    def _finish(self, task_id: int, status: TaskStatus, code: int, summary: str) -> None:
        row = self.bus.get(task_id)
        self.bus.finish(task_id, status, exit_code=code, summary=summary)
        self.bus.post(
            sender=task_id,
            addressee=row.parent,
            kind="task_done",
            summary=summary,
            ref_path=row.dir,
        )
        del self.live[task_id]
        del self.started[task_id]

    def _reap(self) -> None:
        for task_id, process in list(self.live.items()):
            code = process.poll()
            if code is None:
                if self.clock.time() - self.started[task_id] >= self.timeout_s:
                    LOGGER.warning("killing task %s after %ss", task_id, self.timeout_s)
                    process.kill()
                    self._finish(task_id, TaskStatus.TIMEOUT, -9, "killed after timeout")
                continue
            status = TaskStatus.COMPLETED if code == 0 else TaskStatus.CRASHED
            self._finish(task_id, status, code, f"exited {code}")

    def _queued_count(self) -> int:
        row = self.bus.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks WHERE status = ?",
            (TaskStatus.QUEUED.value,),
        ).fetchone()
        return int(row["n"])

    def tick(self) -> None:
        self._start_queued()
        self._reap()

    def run_until_idle(self) -> None:
        while True:
            self.tick()
            if not self.live and self._queued_count() == 0:
                return
            self.clock.sleep(self.poll_s)

    def shutdown(self) -> None:
        for task_id, process in list(self.live.items()):
            process.kill()
            self._finish(task_id, TaskStatus.ABANDONED, -9, "abandoned at shutdown")
