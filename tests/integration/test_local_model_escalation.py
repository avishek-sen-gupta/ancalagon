import json
import os
import pathlib

import pytest

from ancalagon.answer_command import answer_command
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.bus import Bus
from ancalagon.clock.system_clock import SystemClock
from ancalagon.cli import main

MODEL = os.environ.get("ANCALAGON_LOCAL_MODEL", "")


def _config(tmp_path: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{write_root}"]

[agent]
root_behaviour = \"\"\"
You answer a question you have been asked. You have already asked for guidance and
been given it; the guidance is the last message. Call submit_answer with what you
decided, and nothing else.
\"\"\"

[model]
name = "{MODEL}"
num_retries = 1
request_timeout_s = 300
max_tokens = 1024

[budget]
turns = 4
tool_calls = 8

[limits]
max_concurrent_agents = 1
agent_timeout_s = 600
max_depth = 0
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 400

[tools]
enabled = ["need_input", "submit_answer"]

[run]
run_dir = "{run_dir}"
goal_file = ""
contract_module = ""
contract_class = ""
""")
    return config


@pytest.mark.skipif(
    not MODEL,
    reason="set ANCALAGON_LOCAL_MODEL, e.g. ollama_chat/qwen2.5:14b, to run this",
)
def test_a_real_model_asks_a_question_and_acts_on_the_answer(tmp_path: pathlib.Path):
    run_dir = tmp_path / "ws" / "runs" / "asked"
    config = _config(tmp_path, run_dir)
    goal = (
        "Decide whether to keep both captions or pick one. You do not have the captions "
        "and cannot obtain them, so you must call need_input to ask which is wanted."
    )

    assert main(config, goal) == 0
    bus = Bus.open(run_dir / "bus.db", SystemClock())
    assert any(e.status is AgentStatus.NEEDS_INPUT for e in bus.history(1)), (
        "the model did not ask; local models vary, and this test is about the resumed "
        "transcript being accepted, so re-run or use a stronger model"
    )
    asked = json.loads((run_dir / "tasks" / "root" / "outcome.json").read_text())
    assert asked["kind"] == "needs_input"
    assert asked["question"].strip() != ""

    assert answer_command(run_dir, 1, "Keep both captions.") == 0
    assert main(config, goal) == 0

    answered = json.loads((run_dir / "tasks" / "root" / "outcome.json").read_text())
    assert answered["kind"] in ("completed", "exhausted")
    said = json.dumps(answered).lower()
    assert "both" in said

    lines = [
        json.loads(l)
        for l in (run_dir / "tasks" / "root" / "transcript.jsonl").read_text().splitlines()
    ]
    answer_at = [
        i for i, l in enumerate(lines) if l["blocks"][0].get("text") == "Keep both captions."
    ]
    assert len(answer_at) == 1
    assert len(lines) > answer_at[0] + 1, "the model was resumed but never replied"
