import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class ToolResultBlock(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[BlockKind.TOOL_RESULT] = BlockKind.TOOL_RESULT
    tool_use_id: str
    content: str
    is_error: bool = False
