# Where a function lives: the module path a role named, and the name inside it.
import pydantic


class FunctionRef(pydantic.BaseModel, frozen=True):
    module: str
    name: str
