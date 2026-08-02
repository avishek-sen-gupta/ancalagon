import pydantic

from ancalagon.contracts.block import Block
from ancalagon.contracts.role import Role


class Message(pydantic.BaseModel, frozen=True):
    role: Role
    blocks: list[Block]
    agent: int
    seq: int
    ts: str
