import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class Text(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TEXT] = BlockKind.TEXT
    text: str
