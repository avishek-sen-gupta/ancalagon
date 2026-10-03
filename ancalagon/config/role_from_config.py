# One [roles.*] table exactly as TOML presents it, before paths are resolved.
import typing

import pydantic


class ClassRefFromConfig(pydantic.BaseModel, frozen=True):
    module: str = ""
    name: str = ""


class BudgetFromConfig(pydantic.BaseModel, frozen=True):
    turns: int | typing.Literal["infinite"]
    tool_calls: int | typing.Literal["infinite"]


class RoleFromConfig(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: ClassRefFromConfig = ClassRefFromConfig()
    answer: ClassRefFromConfig = ClassRefFromConfig()
    answer_file: ClassRefFromConfig = ClassRefFromConfig()
    run: ClassRefFromConfig = ClassRefFromConfig()
    tools: list[str]
    budget: BudgetFromConfig
    before: dict[str, list[ClassRefFromConfig]] = {}
    after: dict[str, list[ClassRefFromConfig]] = {}
