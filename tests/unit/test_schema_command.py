import io
import json

from ancalagon.schema_command import schema_command


def test_the_schema_names_every_required_table_and_the_role_shape():
    out = io.StringIO()

    assert schema_command(out) == 0

    schema = json.loads(out.getvalue())
    assert sorted(schema["required"]) == [
        "limits",
        "model",
        "run",
        "sandbox",
        "workspace",
    ]
    assert "RawRole" in schema["$defs"]
    assert schema["$defs"]["Strategy"]["enum"] == ["none", "fence"]
    assert "absolute" in schema["properties"]["base"]["description"].lower()
