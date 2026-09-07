# An input contract that names the JSON Schema the agent's answer file must satisfy.
import pathlib

import pydantic


class SchemaGuided(pydantic.BaseModel, frozen=True):
    output_schema: pathlib.PurePath
