import json
import pathlib

import pytest

from ancalagon.cli import main
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.letterbox.file_letterbox import NOTES, PATTERN
from ancalagon.session import NOTE_PREFIX
from tests.integration.prepared_run import prepared_run_dir
from tests.integration.scripted_model import ScriptedModel

GOAL = "Say what the bus does."

NOTE = "keep every field flat"

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
behaviour = "You answer the goal."
tools = ["submit_answer"]

[roles.root.budget]
turns = 4
tool_calls = 8

[run]
goal_file = "{goal_file}"
input_file = ""
role = "root"
"""


def _config(tmp_path: pathlib.Path) -> pathlib.Path:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(GOAL)
    config = tmp_path / "ancalagon.toml"
    config.write_text(CONFIG.format(write_root=write_root, goal_file=goal_file))
    return config


def test_a_note_left_before_the_run_reaches_a_real_worker_on_its_first_turn(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    run_dir = tmp_path / "ws" / "runs" / "noted"
    task_dir = run_dir / "tasks" / "root"
    (task_dir / NOTES).mkdir(parents=True)
    (task_dir / NOTES / "20260908T120000000000.txt").write_text(NOTE)

    def decide(goal: str, turn: int) -> list[ToolUse]:
        return [
            ToolUse(id=f"s{turn}", name="submit_answer", arguments=json.dumps({"text": "flat"}))
        ]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")

    try:
        assert main(_config(tmp_path), prepared_run_dir(run_dir)) == 0
    finally:
        model.close()

    delivered = f"{NOTE_PREFIX}{NOTE}"
    assert delivered in model.requests[0]

    lines = [json.loads(line) for line in (task_dir / "transcript.jsonl").read_text().splitlines()]
    assert [line["role"] for line in lines[:2]] == ["user", "user"]
    assert lines[1]["blocks"] == [{"kind": "text", "text": delivered}]

    assert list((task_dir / NOTES).glob(PATTERN)) == []
    outcome = json.loads((task_dir / "outcome-1.json").read_text())
    assert outcome["kind"] == "completed"
    assert outcome["value"] == {"text": "flat"}
