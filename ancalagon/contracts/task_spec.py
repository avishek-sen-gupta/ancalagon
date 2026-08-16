# What a worker reads from spec.json: the scalars, without the input it cannot type.
import pydantic

from ancalagon.contracts.role import Role


class TaskSpec(pydantic.BaseModel, frozen=True):
    task_id: str
    role: Role
    goal: str
