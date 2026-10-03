# What a tool tells the model about itself. The parameters stay a class until the wire.
import pydantic


class ToolSchema(pydantic.BaseModel, frozen=True):
    name: str
    description: str
    parameters: type[pydantic.BaseModel]
