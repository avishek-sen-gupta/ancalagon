# Where a function lives: the dotted module a role named, and the name inside it.
import pydantic

from ancalagon.contracts.dotted import DOTTED, IDENTIFIER


class FunctionRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=DOTTED)
    name: str = pydantic.Field(pattern=IDENTIFIER)
