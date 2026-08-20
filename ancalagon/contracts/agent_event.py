# One observation about an agent. Never updated, never deleted.
import pydantic

from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource


class AgentEvent(pydantic.BaseModel, frozen=True):
    id: int
    agent: int
    ts: str
    status: AgentStatus
    source: EventSource
    pid: int
    summary: str
