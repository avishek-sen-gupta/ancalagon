# Names one contract class in one module of a task directory, holding no path outside it.
import pydantic


class ClassRef(pydantic.BaseModel, frozen=True):
    module: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.py$")
    name: str = pydantic.Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
