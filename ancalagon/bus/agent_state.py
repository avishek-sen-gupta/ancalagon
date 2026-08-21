# An agent joined to its task and directory: what claiming and queuing actually need.
import pydantic


class AgentState(pydantic.BaseModel, frozen=True):
    agent: int
    task: int
    dir: str
