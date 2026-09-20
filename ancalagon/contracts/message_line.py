# One transcript message, as it goes out to a log queue rather than into the file.
import typing

import pydantic

from ancalagon.contracts.line_kind import LineKind
from ancalagon.contracts.message import Message


class MessageLine(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[LineKind.MESSAGE] = LineKind.MESSAGE
    message: Message
