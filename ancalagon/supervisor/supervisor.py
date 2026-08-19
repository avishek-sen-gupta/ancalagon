# Spawns, reaps and kills workers. Never retries -- a crash is reported and the parent decides.
import logging
import pathlib

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import Bus
from ancalagon.bus.event_source import EventSource
from ancalagon.clock.clock import Clock
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.timed_out import TimedOut
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner

LOGGER = logging.getLogger(__name__)


def _crashed(reason: str) -> Failed:
    return Failed(error=reason, summary=reason, spent=Budget(turns=0, tool_calls=0))


class Supervisor:
    def __init__(
        self,
        bus: Bus,
        spawner: Spawner,
        max_concurrent: int,
        timeout_s: int,
        clock: Clock,
        poll_s: float = 0.05,
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
            state = claimed[0]
            try:
                process = self.spawner.spawn(pathlib.Path(state.dir), state.agent)
            except OSError as exc:
                LOGGER.exception("spawn failed for agent %s", state.agent)
                self._finish(state.agent, AgentStatus.CRASHED, -1, f"spawn failed: {exc}")
                continue
            self.bus.record(
                state.agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=process.pid
            )
            LOGGER.info("agent %s running as pid %s for %s", state.agent, process.pid, state.dir)
            self.live[state.agent] = process
            self.started[state.agent] = self.clock.time()

    def _finish(self, agent: int, status: AgentStatus, code: int, summary: str) -> None:
        self.bus.record(agent, status, EventSource.SUPERVISOR, exit_code=code, summary=summary)
        self.live.pop(agent, None)
        self.started.pop(agent, None)

    def _write_outcome(self, agent: int, outcome: Outcome) -> None:
        written = pathlib.Path(self.bus.state(agent).dir) / "outcome.json"
        if written.exists():
            return
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(outcome.model_dump_json())

    def _reap(self) -> None:
        for agent, process in list(self.live.items()):
            code = process.poll()
            if code is None:
                if self.clock.time() - self.started[agent] >= self.timeout_s:
                    LOGGER.warning("killing agent %s after %ss", agent, self.timeout_s)
                    process.kill()
                    self._write_outcome(
                        agent,
                        TimedOut(
                            summary=f"killed after {self.timeout_s}s",
                            spent=Budget(turns=0, tool_calls=0),
                        ),
                    )
                    self._finish(agent, AgentStatus.TIMED_OUT, -9, "killed after timeout")
                continue
            status = AgentStatus.EXITED if code == 0 else AgentStatus.CRASHED
            if status is AgentStatus.CRASHED:
                self._write_outcome(agent, _crashed(f"worker exited {code}"))
            LOGGER.info("agent %s %s", agent, status.value)
            self._finish(agent, status, code, f"exited {code}")

    def _wake_idling(self) -> None:
        for task in self.bus.wakeable(self.live):
            if self.bus.newest_agent(task.id) in self.live:
                continue
            self.bus.enqueue(pathlib.Path(task.dir), parent_agent=task.parent_agent)

    def tick(self) -> None:
        self._start_queued()
        self._reap()
        self._wake_idling()

    def run_until_idle(self) -> None:
        while True:
            self.tick()
            if self.live:
                self.clock.sleep(self.poll_s)
                continue
            orphans = [s.agent for s in self.bus.in_flight() if s.agent not in self.live]
            if orphans:
                LOGGER.warning("agents in flight with no live process: %s", orphans)
                for agent in orphans:
                    self.bus.record(
                        agent,
                        AgentStatus.ABANDONED,
                        EventSource.SUPERVISOR,
                        exit_code=-1,
                        summary="orphaned; no live process",
                    )
                return
            if self.bus.queued_count() == 0:
                return
            self.clock.sleep(self.poll_s)

    def shutdown(self) -> None:
        for agent, process in list(self.live.items()):
            process.kill()
            self._finish(agent, AgentStatus.ABANDONED, -9, "abandoned at shutdown")
