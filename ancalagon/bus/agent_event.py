# One observation about an agent. Never updated, never deleted.
import pydantic

from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.event_source import EventSource


class AgentEvent(pydantic.BaseModel, frozen=True):
    id: int
    agent: int
    ts: str
    status: AgentStatus
    source: EventSource
    pid: int
    exit_code: int
    summary: str
