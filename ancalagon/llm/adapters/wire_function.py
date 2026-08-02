import pydantic


class WireFunction(pydantic.BaseModel, frozen=True):
    name: str
    arguments: str
