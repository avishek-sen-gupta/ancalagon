# What a tool needs of a bus: read the run, record what happened, queue a task.
import pathlib
import typing

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.agent_ref import AgentRef
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.no_agent_ref import NoAgentRef


class Bus(typing.Protocol):
    def snapshot(self) -> Snapshot: ...

    def record(
        self,
        agent: int,
        status: AgentStatus,
        source: EventSource,
        pid: int = 0,
        summary: str = "",
        seen_through: int = 0,
    ) -> None: ...

    def enqueue(self, dir: pathlib.PurePath, parent_agent: int) -> AgentRef | NoAgentRef: ...
