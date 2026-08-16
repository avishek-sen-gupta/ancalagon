# What a worker reads from spec.json: the scalars, without the input it cannot type.
import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.role import FREE_TEXT


class TaskSpec(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input_schema: ClassRef = FREE_TEXT
    answer_schema: ClassRef
    budget: Budget
    tools: list[str] = []
