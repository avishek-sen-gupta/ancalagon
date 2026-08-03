# The function half of a wire tool call.
import pydantic


class WireFunction(pydantic.BaseModel, frozen=True):
    name: str
    arguments: str
