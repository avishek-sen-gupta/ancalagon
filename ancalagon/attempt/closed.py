# An attempt whose worker reported a verdict before the supervisor observed the process exit.
import pydantic

from ancalagon.contracts.agent_status import AgentStatus


class Closed(pydantic.BaseModel, frozen=True):
    verdict: AgentStatus
