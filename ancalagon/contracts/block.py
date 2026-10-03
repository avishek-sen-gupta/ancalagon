# The three kinds of content a message can carry, discriminated on kind.
import typing

import pydantic

from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use_from_model import ToolUseFromModel

Block = typing.Annotated[
    Text | ToolUseFromModel | ToolResultBlock, pydantic.Field(discriminator="kind")
]
