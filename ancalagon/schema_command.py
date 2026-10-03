# Writes the config document's JSON Schema, for callers that generate one.
import json
import typing

from ancalagon.config.document_from_config import DocumentFromConfig


def schema_command(out: typing.TextIO) -> int:
    out.write(json.dumps(DocumentFromConfig.model_json_schema(), indent=2) + "\n")
    return 0
