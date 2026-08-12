import pydantic

from ancalagon.contracts.block import Block


class Reply(pydantic.BaseModel, frozen=True):
    blocks: list[Block]
    stop_reason: str
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
