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
    assert {name: sorted(d.get("required", [])) for name, d in schema["$defs"].items()} == {
        "RawBudget": ["tool_calls", "turns"],
        "RawClassRef": [],
        "RawLimits": [
            "agent_timeout_s",
            "compact_above_tokens",
            "keep_recent_messages",
            "max_concurrent_agents",
            "max_depth",
            "summary_chars",
        ],
        "RawLog": [],
        "RawModel": ["allowed_domains", "max_tokens", "name", "num_retries", "request_timeout_s"],
        "RawRole": ["behaviour", "budget", "tools"],
        "RawRun": ["goal_file", "input_file", "role"],
        "RawSandbox": ["strategy"],
        "RawWeb": [],
        "RawWorkspace": ["home", "read_roots", "write_roots"],
        "Strategy": [],
    }
