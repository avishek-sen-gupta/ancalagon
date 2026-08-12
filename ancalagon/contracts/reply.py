# What one model call returned, and what it consumed.
import pydantic

from ancalagon.contracts.block import Block
from ancalagon.contracts.call_usage import CallUsage


class Reply(pydantic.BaseModel, frozen=True):
    blocks: list[Block]
    stop_reason: str
    usage: CallUsage = CallUsage()
