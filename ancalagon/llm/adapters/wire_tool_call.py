import pydantic

from ancalagon.llm.adapters.wire_function import WireFunction


class WireToolCall(pydantic.BaseModel, frozen=True):
    id: str
    type: str
    function: WireFunction
