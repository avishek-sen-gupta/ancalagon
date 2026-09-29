# Writes the config document's JSON Schema, for callers that generate one.
import json
import typing

from ancalagon.config.raw_config import RawConfig


def schema_command(out: typing.TextIO) -> int:
    out.write(json.dumps(RawConfig.model_json_schema(), indent=2) + "\n")
    return 0
