import json
import pathlib

import pytest

from ancalagon.cli import main
from ancalagon.contracts.tool_use import ToolUse
from tests.integration.prepared_run import prepared_run_dir
from tests.integration.scripted_model import ScriptedModel

GOAL = "Record the module and the values it holds."

SCHEMA = {
    "type": "object",
    "required": ["name", "values"],
    "properties": {
        "name": {"type": "string"},
        "values": {"type": "array", "items": {"type": "integer"}},
    },
}

CONFIG = """
[workspace]
write_root = "{write_root}"
read_roots = ["{write_root}"]

[model]
name = "openai/scripted"
num_retries = 0
request_timeout_s = 30
max_tokens = 512
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 400

[sandbox]
strategy = "none"

[roles.root]
behaviour = "You build the answer in a file."
input = {{ module = "ancalagon.contracts.schema_guided", name = "SchemaGuided" }}
answer = {{ module = "ancalagon.contracts.answer_file", name = "AnswerFile" }}
tools = ["write_file", "edit_json", "submit_answer_as_file"]
budget = {{ turns = 6, tool_calls = 10 }}

[roles.root.before]
submit_answer_as_file = [
  {{ module = "ancalagon.tools.submit.adheres_to_schema", name = "adheres_to_schema" }},
]

[run]
goal_file = "{goal_file}"
input_file = "{input_file}"
role = "root"
"""


def _config(tmp_path: pathlib.Path, write_root: pathlib.Path) -> pathlib.Path:
    write_root.mkdir(parents=True, exist_ok=True)
    (write_root / "record.schema.json").write_text(json.dumps(SCHEMA))
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(GOAL)
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"output_schema": str(write_root / "record.schema.json")}))
    config = tmp_path / "ancalagon.toml"
    config.write_text(
        CONFIG.format(write_root=write_root, goal_file=goal_file, input_file=input_file)
    )
    return config


def test_an_agent_builds_its_answer_in_a_file_and_the_schema_hook_gates_submitting_it(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    write_root = tmp_path / "ws"
    answer = write_root / "record.json"
    run_dir = write_root / "runs" / "filed"
    submitting = json.dumps(
        {"status": "complete", "summary": "one module and its values", "path": str(answer)}
    )
    script = {
        0: ToolUse(
            id="w0",
            name="write_file",
            arguments=json.dumps({"path": str(answer), "content": "{}"}),
        ),
        1: ToolUse(
            id="e1",
            name="edit_json",
            arguments=json.dumps(
                {
                    "path": str(answer),
                    "op": "set",
                    "pointer": "/name",
                    "value": '"com.example.utils"',
                }
            ),
        ),
        2: ToolUse(id="s2", name="submit_answer_as_file", arguments=submitting),
        3: ToolUse(
            id="e3",
            name="edit_json",
            arguments=json.dumps(
                {"path": str(answer), "op": "set", "pointer": "/values", "value": "[1, 2]"}
            ),
        ),
        4: ToolUse(id="s4", name="submit_answer_as_file", arguments=submitting),
    }
    called: list[str] = []

    def decide(goal: str, turn: int) -> list[ToolUse]:
        called.append(script[turn].name)
        return [script[turn]]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")

    try:
        assert main(_config(tmp_path, write_root), prepared_run_dir(run_dir)) == 0
    finally:
        model.close()

    assert called == [
        "write_file",
        "edit_json",
        "submit_answer_as_file",
        "edit_json",
        "submit_answer_as_file",
    ]
    assert json.loads(answer.read_text()) == {"name": "com.example.utils", "values": [1, 2]}

    outcome = json.loads((run_dir / "tasks" / "root" / "outcome-1.json").read_text())
    assert outcome["kind"] == "completed"
    assert outcome["value"] == {
        "status": "complete",
        "summary": "one module and its values",
        "path": str(answer),
    }
    assert outcome["spent"] == {"turns": 5, "tool_calls": 3}

    said = (run_dir / "tasks" / "root" / "transcript.jsonl").read_text()
    assert "'values' is a required property" in said
