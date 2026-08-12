# One message in provider wire format, typed so the payload never becomes an untyped dict.
import pydantic

from ancalagon.llm.adapters.wire_text_block import WireTextBlock
from ancalagon.llm.adapters.wire_tool_call import WireToolCall


class WireMessage(pydantic.BaseModel, frozen=True):
    role: str
    content: str | tuple[WireTextBlock, ...] = ""
    tool_calls: list[WireToolCall] = []
    tool_call_id: str = ""
