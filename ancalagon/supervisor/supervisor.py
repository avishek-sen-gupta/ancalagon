# Spawns, reaps and kills workers. Never retries -- a crash is reported and the parent decides.
import datetime
import logging
import pathlib

from ancalagon.attempt.reported import Reported
from ancalagon.bus.agent_state import AgentState
from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.timed_out import TimedOut
from ancalagon.supervisor.liveness import Liveness
from ancalagon.supervisor.os_liveness import OS_LIVENESS
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
        liveness: Liveness = OS_LIVENESS,
    ):
        self.bus = bus
        self.spawner = spawner
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self.clock = clock
        self.liveness = liveness
        self.live: dict[int, Process] = {}
        self.started: dict[int, float] = {}

    def _start_queued(self) -> None:
        free = self.max_concurrent - len(self.live)
        if free <= 0:
            return
        for state in self.bus.claim(limit=free):
            self._spawn(state)

    def _spawn(self, state: AgentState) -> None:
        try:
            process = self.spawner.spawn(pathlib.Path(state.dir), state.agent)
        except OSError as exc:
            LOGGER.exception("spawn failed for agent %s", state.agent)
            self._finish(state.agent, AgentStatus.CRASHED, -1, f"spawn failed: {exc}")
            return
        self.bus.record(state.agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=process.pid)
        LOGGER.info("agent %s running as pid %s for %s", state.agent, process.pid, state.dir)
        self.live = {**self.live, state.agent: process}
        self.started = {**self.started, state.agent: self.clock.time()}

    def _finish(self, agent: int, status: AgentStatus, code: int, summary: str) -> None:
        self.bus.record(agent, status, EventSource.SUPERVISOR, exit_code=code, summary=summary)
        self.live = {a: p for a, p in self.live.items() if a != agent}
        self.started = {a: s for a, s in self.started.items() if a != agent}

    def _write_outcome(self, agent: int, outcome: Outcome) -> None:
        written = pathlib.Path(self.bus.state(agent).dir) / "outcome.json"
        if written.exists():
            return
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(outcome.model_dump_json())

    def _reap_timeout(self, agent: int, process: Process) -> None:
        if self.clock.time() - self.started[agent] < self.timeout_s:
            return
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

    def _reap(self) -> None:
        for agent, process in list(self.live.items()):
            self._reap_one(agent, process)

    def _reap_one(self, agent: int, process: Process) -> None:
        match process.poll():
            case None:
                self._reap_timeout(agent, process)
            case 0:
                LOGGER.info("agent %s %s", agent, AgentStatus.EXITED.value)
                self._finish(agent, AgentStatus.EXITED, 0, "exited 0")
            case code:
                self._write_outcome(agent, _crashed(f"worker exited {code}"))
                LOGGER.info("agent %s %s", agent, AgentStatus.CRASHED.value)
                self._finish(agent, AgentStatus.CRASHED, code, f"exited {code}")

    def _wake_idling(self) -> None:
        asleep = [
            task for task in self.bus.wakeable() if self.bus.newest_agent(task.id) not in self.live
        ]
        for task in asleep:
            self.bus.enqueue(pathlib.Path(task.dir), parent_agent=task.parent_agent)

    def tick(self) -> None:
        self._start_queued()
        self._reap()
        self._wake_idling()

    def resolve_stale(self) -> None:
        for state in self.bus.unreaped():
            self._resolve_one(state.agent)

    def _resolve_one(self, agent: int) -> None:
        if isinstance(self.bus.attempt(agent), Reported):
            self.bus.record(
                agent,
                AgentStatus.EXITED,
                EventSource.SUPERVISOR,
                summary="closed at startup; worker had reported",
            )
            return
        running = [e for e in self.bus.history(agent) if e.status is AgentStatus.RUNNING]
        if running and self.liveness.is_running(running[-1].pid):
            self._resolve_running(agent, running[-1])
            return
        self.bus.record(
            agent,
            AgentStatus.CRASHED,
            EventSource.SUPERVISOR,
            exit_code=-1,
            summary="no live process at startup",
        )

    def _resolve_running(self, agent: int, running: AgentEvent) -> None:
        elapsed = (self.clock.now() - datetime.datetime.fromisoformat(running.ts)).total_seconds()
        if elapsed <= self.timeout_s:
            return
        self.liveness.kill(running.pid)
        self._write_outcome(
            agent,
            TimedOut(
                summary=f"killed after {self.timeout_s}s at startup",
                spent=Budget(turns=0, tool_calls=0),
            ),
        )
        self.bus.record(
            agent,
            AgentStatus.TIMED_OUT,
            EventSource.SUPERVISOR,
            exit_code=-9,
            summary=f"killed after {self.timeout_s}s at startup",
        )

    def run_until_idle(self) -> None:
        self.resolve_stale()
        while True:
            self.tick()
            if self.live:
                self.clock.sleep(self.poll_s)
                continue
            if self.bus.queued_count() == 0:
                return
            self.clock.sleep(self.poll_s)

    def shutdown(self) -> None:
        self.live = {}
        self.started = {}
