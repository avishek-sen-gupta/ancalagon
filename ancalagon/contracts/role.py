# Everything about an agent except its task: what it is told, what it works to, what it may use.
import collections.abc

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.function_ref import FunctionRef

FREE_TEXT = ClassRef(module="ancalagon.contracts.free_text", name="FreeText")


class Role(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: ClassRef = FREE_TEXT
    answer: ClassRef = FREE_TEXT
    tools: tuple[str, ...]
    budget: Budget
    before: collections.abc.Mapping[str, tuple[FunctionRef, ...]] = {}
    after: collections.abc.Mapping[str, tuple[FunctionRef, ...]] = {}
