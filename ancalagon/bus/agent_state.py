# An agent joined to its task and its latest event: what callers actually ask for.
import pydantic

from ancalagon.contracts.agent_status import AgentStatus


class AgentState(pydantic.BaseModel, frozen=True):
    agent: int
    task: int
    dir: str
    parent_agent: int
    status: AgentStatus
    pid: int
    exit_code: int
    summary: str
