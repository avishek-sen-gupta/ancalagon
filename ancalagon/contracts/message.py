import pydantic

from ancalagon.contracts.block import Block
from ancalagon.contracts.message_role import MessageRole


class Message(pydantic.BaseModel, frozen=True):
    role: MessageRole
    blocks: list[Block]
    agent: int
    seq: int
    ts: str
