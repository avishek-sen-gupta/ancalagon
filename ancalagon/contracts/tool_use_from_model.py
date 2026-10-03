# A tool call exactly as the model asked for it: a name that may match nothing, and
# arguments that are still text. Resolved against the registry before anything runs.
import typing

import pydantic

from ancalagon.contracts.block_kind import BlockKind


class ToolUseFromModel(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["tool_use"] = BlockKind.TOOL_USE.value
    id: str
    name: str
    arguments: str
