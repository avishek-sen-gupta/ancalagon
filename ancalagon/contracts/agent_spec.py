# What a caller declares when creating work; a worker reads TaskSpec instead.
import typing

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.free_text_ref import FREE_TEXT_REF

InT = typing.TypeVar("InT", bound=pydantic.BaseModel, covariant=True)


class AgentSpec(pydantic.BaseModel, typing.Generic[InT], frozen=True):
    task_id: str
    behaviour: str
    goal: str
    input: InT
    input_schema: ClassRef = FREE_TEXT_REF
    answer_schema: ClassRef
    budget: Budget
    tools: list[str] = []
