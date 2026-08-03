# What a caller declares when creating work; a worker reads TaskSpec instead.
import typing

import pydantic

from ancalagon.contracts.budget import Budget

InT = typing.TypeVar("InT", bound=pydantic.BaseModel, covariant=True)


class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input: InT
    output: str
    budget: Budget
    tools: list[str] = []
