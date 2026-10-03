# A role exactly as it is written and stored: the refs it names, and a budget as a plain count.
import typing

import pydantic

from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.no_answer_file import NO_ANSWER_FILE
from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.role import FREE_TEXT


class SerialisableBudget(pydantic.BaseModel, frozen=True):
    turns: int | typing.Literal["infinite"]
    tool_calls: int | typing.Literal["infinite"]


class SerialisableRole(pydantic.BaseModel, frozen=True):
    behaviour: str
    profile: ClassRef
    input: ClassRef = FREE_TEXT
    answer: ClassRef = FREE_TEXT
    answer_file: ClassRef = NO_ANSWER_FILE
    run: FunctionRef = NO_RUN
    tools: tuple[str, ...]
    budget: SerialisableBudget
    before: dict[str, tuple[FunctionRef, ...]] = {}
    after: dict[str, tuple[FunctionRef, ...]] = {}
