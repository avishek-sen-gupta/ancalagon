# An attempt whose worker left an outcome behind, so the attempt spoke.
import pydantic

from ancalagon.contracts.agent_status import AgentStatus


class Closed(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
