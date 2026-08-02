import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class ToolUse(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TOOL_USE] = BlockKind.TOOL_USE
    id: str
    name: str
    arguments: str
