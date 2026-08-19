# An attempt a parent has collected, from either its own outcome or one the supervisor synthesised.
import pydantic

from ancalagon.bus.agent_status import AgentStatus


class Collected(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
    spoke: bool
