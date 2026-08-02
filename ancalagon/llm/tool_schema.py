import pydantic


class ToolSchema(pydantic.BaseModel, frozen=True):
    name: str
    description: str
    parameters_json: str
