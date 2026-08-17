# The contracts ancalagon.example.toml's component_analyst role is declared against.
import pydantic


class ComponentQuery(pydantic.BaseModel, frozen=True):
    area: str = pydantic.Field(description="The part of the codebase to investigate.")


class Component(pydantic.BaseModel, frozen=True):
    name: str
    description: str
    files: list[str]
    invariants: list[str]
