# The three kinds of content a message can carry, discriminated on kind.
import typing

import pydantic

from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse

Block = typing.Annotated[Text | ToolUse | ToolResultBlock, pydantic.Field(discriminator="kind")]
