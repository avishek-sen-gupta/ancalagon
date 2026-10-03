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
    assert "RoleFromConfig" in schema["$defs"]
    assert schema["$defs"]["Strategy"]["enum"] == ["none", "fence"]
    assert "absolute" in schema["properties"]["base"]["description"].lower()
    assert {name: sorted(d.get("required", [])) for name, d in schema["$defs"].items()} == {
        "BudgetFromConfig": ["tool_calls", "turns"],
        "ClassRefFromConfig": [],
        "LimitsFromConfig": [
            "agent_timeout_s",
            "compact_above_tokens",
            "keep_recent_messages",
            "max_concurrent_agents",
            "max_depth",
            "summary_chars",
        ],
        "LogFromConfig": [],
        "ModelFromConfig": [
            "allowed_domains",
            "max_tokens",
            "name",
            "num_retries",
            "request_timeout_s",
        ],
        "RoleFromConfig": ["behaviour", "budget", "tools"],
        "RunFromConfig": ["goal_file", "input_file", "role"],
        "SandboxFromConfig": ["strategy"],
        "WebFromConfig": [],
        "WorkspaceFromConfig": ["home", "read_roots", "write_roots"],
        "Strategy": [],
    }
