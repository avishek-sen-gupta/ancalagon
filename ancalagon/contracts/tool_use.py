# A model's request to call a tool. Arguments stay JSON text until the tool validates them.
import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class ToolUse(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["tool_use"] = BlockKind.TOOL_USE.value
    id: str
    name: str
    arguments: str
