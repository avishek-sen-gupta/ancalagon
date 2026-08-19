# An attempt the supervisor observed ending without the worker ever reporting a verdict.
import pydantic

from ancalagon.bus.agent_status import AgentStatus


class Lost(pydantic.BaseModel, frozen=True):
    close: AgentStatus
