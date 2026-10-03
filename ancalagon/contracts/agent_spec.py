# What a caller declares when creating work; a worker reads TaskSpec instead.
import pydantic

from ancalagon.contracts.serialisable_role import SerialisableRole


class AgentSpec[InT: pydantic.BaseModel](pydantic.BaseModel, frozen=True):
    task_id: str
    role: SerialisableRole
    goal: str
    input: InT
