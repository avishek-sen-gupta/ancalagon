import json
import pathlib

import pytest

from ancalagon.answer_command import answer_command
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import Bus
from ancalagon.cli import main
from ancalagon.contracts.tool_use import ToolUse
from tests.integration.scripted_model import ScriptedModel

AMBIGUOUS = "The ambiguous half."
CLEAR = "The clear half."
ROOT = "Investigate both halves."


def _call(id: str, name: str, **arguments: str | int) -> ToolUse:
    return ToolUse(id=id, name=name, arguments=json.dumps(arguments))


def _delegate(id: str, task_id: str, goal: str) -> ToolUse:
    return _call(
        id,
        "delegate",
        task_id=task_id,
        behaviour="You investigate.",
        goal=goal,
        input_json='{"text": "go"}',
        turns=4,
        tool_calls=8,
    )


def _config(tmp_path: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{write_root}"]

[agent]
root_behaviour = "You coordinate."

[model]
name = "openai/scripted"
num_retries = 0
request_timeout_s = 30
max_tokens = 512

[budget]
turns = 6
tool_calls = 20

[limits]
max_concurrent_agents = 2
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 400

[tools]
enabled = []

[run]
run_dir = "{run_dir}"
goal_file = ""
contract_module = ""
contract_class = ""
""")
    return config


def test_a_scripted_model_drives_the_escalation_through_real_worker_processes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    run_dir = tmp_path / "ws" / "runs" / "escalation"

    def decide(goal: str, turn: int) -> list[ToolUse]:
        if goal == AMBIGUOUS:
            if turn == 0:
                return [_call("n1", "need_input", question="keep both captions or pick one?")]
            return [_call("s3", "submit_answer", text="ambiguous half: kept both")]
        if goal == CLEAR:
            return [_call("s1", "submit_answer", text="the clear half is fine")]
        if turn == 0:
            return [
                _delegate("d1", "child-a", AMBIGUOUS),
                _delegate("d2", "child-b", CLEAR),
            ]
        if turn == 1:
            return [_call("n2", "need_input", question="a child is stuck; keep both?")]
        if turn == 2:
            return [_call("a1", "answer_task", task=2, answer="keep both")]
        return [_call("s2", "submit_answer", text="both halves handled")]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")
    config = _config(tmp_path, run_dir)

    try:
        assert main(config, ROOT) == 0
        bus = Bus.open(run_dir / "bus.db")

        def asked(agent: int) -> bool:
            return any(e.status is AgentStatus.NEEDS_INPUT for e in bus.history(agent))

        assert asked(1)
        assert asked(2)
        assert any(e.status is AgentStatus.COMPLETED for e in bus.history(3))

        assert answer_command(run_dir, 1, "keep both") == 0
        assert main(config, ROOT) == 0

        resumed_root = bus.active_for(run_dir / "tasks" / "root")
        assert resumed_root == []
        assert any(e.status is AgentStatus.COMPLETED for e in bus.history(4))

        answered = json.loads((run_dir / "tasks" / "root" / "outcome.json").read_text())
        assert answered["kind"] == "completed"
        assert answered["value"]["text"] == "both halves handled"

        child_dir = run_dir / "tasks" / "child-a"
        lines = [json.loads(l) for l in (child_dir / "transcript.jsonl").read_text().splitlines()]
        answered_at = [i for i, l in enumerate(lines) if l["blocks"][0].get("text") == "keep both"]
        assert len(answered_at) == 1
        assert any(
            b.get("name") == "need_input" for l in lines[: answered_at[0]] for b in l["blocks"]
        )
        resumed_child = json.loads((child_dir / "outcome.json").read_text())
        assert resumed_child["kind"] == "completed"
        assert resumed_child["value"]["text"] == "ambiguous half: kept both"
    finally:
        model.close()
