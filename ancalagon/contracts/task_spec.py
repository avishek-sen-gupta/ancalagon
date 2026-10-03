# What a worker reads from spec.json: the scalars, without the input it cannot type.
import pydantic

from ancalagon.contracts.serialisable_role import SerialisableRole


class TaskSpec(pydantic.BaseModel, frozen=True):
    task_id: str
    role: SerialisableRole
    goal: str
