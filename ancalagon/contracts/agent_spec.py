import typing

import pydantic

from ancalagon.contracts.budget import Budget

InT = typing.TypeVar("InT", bound=pydantic.BaseModel)


class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input: InT
    output: str
    budget: Budget
    tools: list[str] = []
