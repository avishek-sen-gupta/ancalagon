# What a caller declares when creating work; a worker reads TaskSpec instead.
import typing

import pydantic

from ancalagon.contracts.role import Role

InT = typing.TypeVar("InT", bound=pydantic.BaseModel, covariant=True)


class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    role: Role
    goal: str
    input: InT
