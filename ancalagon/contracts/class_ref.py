# Names one contract class by the dotted module that defines it.
import pydantic

from ancalagon.contracts.dotted import DOTTED, IDENTIFIER


class ClassRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=DOTTED)
    name: str = pydantic.Field(pattern=IDENTIFIER)
