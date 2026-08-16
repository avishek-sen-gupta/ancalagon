# Names one contract class by the module path that defines it.
import pydantic


class ClassRef(pydantic.BaseModel, frozen=True):
    module: str
    name: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
