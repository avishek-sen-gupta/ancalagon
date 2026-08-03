# Builds a tool schema from a pydantic model, so every tool declares itself the same way.
import json

import pydantic

from ancalagon.llm.tool_schema import ToolSchema


def schema_of(name: str, description: str, model: type[pydantic.BaseModel]) -> ToolSchema:
    return ToolSchema(
        name=name, description=description, parameters_json=json.dumps(model.model_json_schema())
    )
