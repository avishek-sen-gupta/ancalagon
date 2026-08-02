import pydantic

from ancalagon.contracts.budget import Budget


class TaskSpec(pydantic.BaseModel, frozen=True):
    task_id: str
    behaviour: str
    goal: str
    output: str
    budget: Budget
    tools: list[str] = []
