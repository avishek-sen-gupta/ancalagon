import pydantic

from ancalagon.llm.adapters.wire_tool_call import WireToolCall


class WireMessage(pydantic.BaseModel, frozen=True):
    role: str
    content: str = ""
    tool_calls: list[WireToolCall] = []
    tool_call_id: str = ""
