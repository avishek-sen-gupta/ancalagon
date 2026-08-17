# What a caller declares when creating work; a worker reads TaskSpec instead.
import pydantic

from ancalagon.contracts.role import Role


class AgentSpec[InT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    task_id: str
    role: Role
    goal: str
    input: InT
