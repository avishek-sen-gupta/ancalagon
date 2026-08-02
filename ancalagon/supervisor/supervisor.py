import logging
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.bus.task_status import TaskStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.timed_out import TimedOut
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
        for _ in range(free):
            claimed = self.bus.claim(limit=1)
            if not claimed:
                return
            row = claimed[0]
            try:
                process = self.spawner.spawn(pathlib.Path(row.dir), row.id)
            except Exception as exc:
                LOGGER.exception("spawn failed for task %s", row.id)
                self.bus.finish(row.id, TaskStatus.CRASHED, exit_code=-1, summary=str(exc))
                self.bus.post(
                    sender=row.id,
                    addressee=row.parent,
                    kind="task_done",
                    summary=f"spawn failed: {exc}",
                    ref_path=row.dir,
                )
                continue
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

    def _write_timeout_outcome(self, task_id: int) -> None:
        outcome = pathlib.Path(self.bus.get(task_id).dir) / "outcome.json"
        if outcome.exists():
            return
        outcome.parent.mkdir(parents=True, exist_ok=True)
        outcome.write_text(
            TimedOut(
                summary=f"killed after {self.timeout_s}s",
                spent=Budget(turns=0, tool_calls=0),
            ).model_dump_json()
        )

    def _reap(self) -> None:
        for task_id, process in list(self.live.items()):
            code = process.poll()
            if code is None:
                if self.clock.time() - self.started[task_id] >= self.timeout_s:
                    LOGGER.warning("killing task %s after %ss", task_id, self.timeout_s)
                    process.kill()
                    self._write_timeout_outcome(task_id)
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
            outstanding = [r.id for r in self.bus.running() if r.id not in self.live]
            if not self.live and not outstanding and self._queued_count() == 0:
                return
            if not self.live and outstanding:
                LOGGER.warning("orphaned running rows with no live process: %s", outstanding)
                for task_id in outstanding:
                    self.bus.finish(task_id, TaskStatus.ABANDONED, -1, "orphaned; no live process")
                return
            self.clock.sleep(self.poll_s)

    def shutdown(self) -> None:
        for task_id, process in list(self.live.items()):
            process.kill()
            self._finish(task_id, TaskStatus.ABANDONED, -9, "abandoned at shutdown")
