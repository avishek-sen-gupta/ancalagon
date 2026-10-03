# The two things a run says about itself, discriminated on kind.
import typing

import pydantic

from ancalagon.contracts.lifecycle_line import LifecycleLine
from ancalagon.contracts.message_line import MessageLine

Line = typing.Annotated[LifecycleLine | MessageLine, pydantic.Field(discriminator="kind")]
