# An attempt whose worker has written its own verdict but the supervisor has not yet reaped it.
import pydantic

from ancalagon.bus.agent_status import AgentStatus


class Reported(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
