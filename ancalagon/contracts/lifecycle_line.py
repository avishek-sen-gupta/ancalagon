# One agent status change, as it goes out to a log queue rather than into the bus.
import typing

import pydantic

from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.line_kind import LineKind


class LifecycleLine(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[LineKind.LIFECYCLE] = LineKind.LIFECYCLE
    agent: int
    status: AgentStatus
    source: EventSource
    pid: int
    summary: str
