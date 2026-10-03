import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class Text(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["text"] = BlockKind.TEXT.value
    text: str
