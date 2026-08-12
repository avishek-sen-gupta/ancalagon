# One text block in provider wire format, optionally marked as a prompt-cache breakpoint.
import pydantic


class WireTextBlock(pydantic.BaseModel, frozen=True):
    type: str
    text: str
    cache_control: dict[str, str] = {}
