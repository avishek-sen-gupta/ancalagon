import pydantic

from ancalagon.contracts.block import Block


class Reply(pydantic.BaseModel, frozen=True):
    blocks: list[Block]
    stop_reason: str
