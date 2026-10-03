import json
import pathlib

import pytest

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.cli import main
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.tool_use_from_model import ToolUseFromModel
from ancalagon.fs.real_file_system import RealFileSystem
from tests.integration.prepared_run import prepared_run_dir
from tests.integration.scripted_model import ScriptedModel

GOAL = "Keep a running note and stand by."

CONFIG = """
[workspace]
home = "{write_root}"
write_roots = ["{write_root}"]
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
profile = {{ module = "ancalagon.profiles.standing", name = "Standing" }}
behaviour = "You keep a note and stand by."
tools = ["append_file", "read_file"]

[roles.root.budget]
turns = 6
tool_calls = 12

[run]
goal_file = "{goal_file}"
input_file = ""
role = "root"
"""


def _config(tmp_path: pathlib.Path, write_root: pathlib.Path) -> pathlib.PurePath:
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(GOAL)
    config = tmp_path / "ancalagon.toml"
    config.write_text(CONFIG.format(write_root=write_root, goal_file=goal_file))
    return pathlib.PurePath(config)


def test_a_standing_agent_never_answers_and_resumes_the_conversation_it_had(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    run_dir = write_root / "runs" / "standing"
    note = run_dir / "note.md"
    asked: list[int] = []

    def decide(goal: str, turn: int) -> list[ToolUseFromModel]:
        asked.append(turn)
        if turn == 0:
            return [
                ToolUseFromModel(
                    id="a0",
                    name="append_file",
                    arguments=json.dumps({"path": str(note), "content": "first pass"}),
                )
            ]
        return [ToolUseFromModel(id=f"i{turn}", name="idle", arguments="{}")]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")
    config = _config(tmp_path, write_root)
    prepared = prepared_run_dir(run_dir)

    try:
        assert main(config, prepared, config_json=False) == 0
        first = json.loads((run_dir / "tasks" / "root" / "outcome-1.json").read_text())

        # Nothing wakes it, so a second invocation is the external loop starting it again.
        assert main(config, prepared, config_json=False) == 0
    finally:
        model.close()

    assert asked == [0, 1, 2]
    assert note.read_text() == "first pass\n"

    # It never answered: both attempts ended idling, with no answer anywhere.
    assert first["kind"] == "idling"
    assert first["summary"] == "idling until something arrives"
    second = json.loads((run_dir / "tasks" / "root" / "outcome-2.json").read_text())
    assert second["kind"] == "idling"
    assert "value" not in first and "value" not in second

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), RealFileSystem())
    assert AgentStatus.IDLING in [e.status for e in bus.history(1)]
    assert AgentStatus.IDLING in [e.status for e in bus.history(2)]
    assert AgentStatus.COMPLETED not in [e.status for e in bus.history(2)]

    # The second agent was handed the first agent's conversation, not a fresh one.
    resumed = json.loads(model.requests[-1])["messages"]
    assert [b["function"]["name"] for m in resumed for b in m.get("tool_calls", [])] == [
        "append_file",
        "idle",
    ]
    offered = [t["function"]["name"] for t in json.loads(model.requests[-1])["tools"]]
    assert sorted(offered) == ["append_file", "idle", "read_file"]
