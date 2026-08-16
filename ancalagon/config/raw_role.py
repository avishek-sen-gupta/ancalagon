# One [roles.*] table exactly as TOML presents it, before paths are resolved.
import pydantic


class RawClassRef(pydantic.BaseModel, frozen=True):
    module: str = ""
    name: str = ""


class RawBudget(pydantic.BaseModel, frozen=True):
    turns: int
    tool_calls: int


class RawRole(pydantic.BaseModel, frozen=True):
    behaviour: str
    input: RawClassRef = RawClassRef()
    answer: RawClassRef = RawClassRef()
    tools: list[str]
    budget: RawBudget
