# The bus an agent has when it runs alone: nothing to read, nothing to queue.
import pathlib

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.bus import Bus
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.no_agent_ref import NoAgentRef

EMPTY = Snapshot(tasks=(), agents_by_task={}, task_by_agent={}, events={}, attempts={})


class NoBus(Bus):
    def snapshot(self) -> Snapshot:
        return EMPTY

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
        seen_through: int = 0,
    ) -> None:
        return None

    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> NoAgentRef:
        return NoAgentRef()


NO_BUS = NoBus()
