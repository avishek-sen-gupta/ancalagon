import json
import pathlib

import pytest

from ancalagon.answer_command import answer_command
from ancalagon.bus.bus import Bus
from ancalagon.cli import main
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.tool_use import ToolUse
from tests.integration.scripted_model import ScriptedModel

AMBIGUOUS = "The ambiguous half."
CLEAR = "The clear half."
ROOT = "Investigate both halves."


def _call(id: str, name: str, **arguments: str | int) -> ToolUse:
    return ToolUse(id=id, name=name, arguments=json.dumps(arguments))


def _delegate(id: str, task_id: str, goal: str) -> ToolUse:
    return ToolUse(
        id=id,
        name="delegate_investigate",
        arguments=json.dumps({"task_id": task_id, "goal": goal, "input": {"text": "go"}}),
    )


def _config(tmp_path: pathlib.Path, run_dir: pathlib.Path, goal: str) -> pathlib.Path:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    goal_file = tmp_path / "goal.md"
    goal_file.write_text(goal)
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
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
max_concurrent_agents = 2
agent_timeout_s = 120
max_depth = 1
compact_above_tokens = 0
keep_recent_messages = 8
summary_chars = 400

[sandbox]
strategy = "none"

[roles.root]
behaviour = "You investigate, delegating a focused subtask to escalate a question."
tools = ["delegate_investigate", "need_input", "answer_task"]

[roles.root.budget]
turns = 6
tool_calls = 20

[roles.investigate]
behaviour = "You investigate."
tools = ["need_input"]

[roles.investigate.budget]
turns = 4
tool_calls = 8

[run]
run_dir = "{run_dir}"
goal_file = "{goal_file}"
input_file = ""
role = "root"
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
    config = _config(tmp_path, run_dir, ROOT)

    try:
        assert main(config) == 0
        bus = Bus.open(run_dir / "bus.db", SystemClock())

        def asked(agent: int) -> bool:
            return any(e.status is AgentStatus.NEEDS_INPUT for e in bus.history(agent))

        assert asked(1)
        assert asked(2)
        assert any(e.status is AgentStatus.COMPLETED for e in bus.history(3))

        assert answer_command(run_dir, 1, "keep both") == 0
        assert main(config) == 0

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


ROOT_IDLE = "Delegate a subtask, then idle until it settles."
CHILD_WORK = "Do the delegated work."


def test_a_supervisor_wakes_an_idling_root_once_its_child_settles(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    run_dir = tmp_path / "ws" / "runs" / "idle-wake"

    def decide(goal: str, turn: int) -> list[ToolUse]:
        if goal == CHILD_WORK:
            return [_call("c1", "submit_answer", text="child settled")]
        if turn == 0:
            return [_delegate("d1", "idle-child", CHILD_WORK)]
        if turn == 1:
            return [_call("i1", "idle")]
        return [_call("s1", "submit_answer", text="resumed after idle")]

    model = ScriptedModel(decide)
    monkeypatch.setenv("OPENAI_BASE_URL", model.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "scripted")
    config = _config(tmp_path, run_dir, ROOT_IDLE)

    try:
        assert main(config) == 0
        bus = Bus.open(run_dir / "bus.db", SystemClock())

        root_task = bus.task(run_dir / "tasks" / "root")
        agents = [
            int(r["id"])
            for r in bus.conn.execute(
                "SELECT id FROM agents WHERE task = ? ORDER BY id", (root_task.id,)
            ).fetchall()
        ]
        assert len(agents) == 2
        first_root, second_root = agents

        assert any(e.status is AgentStatus.IDLING for e in bus.history(first_root))
        assert any(e.status is AgentStatus.COMPLETED for e in bus.history(second_root))

        outcome = json.loads((run_dir / "tasks" / "root" / "outcome.json").read_text())
        assert outcome["kind"] == "completed"
        assert outcome["value"]["text"] == "resumed after idle"

        lines = [
            json.loads(line)
            for line in (run_dir / "tasks" / "root" / "transcript.jsonl").read_text().splitlines()
        ]
        idled = [b for line in lines for b in line["blocks"] if b.get("name") == "idle"]
        resumed = [
            b
            for line in lines
            for b in line["blocks"]
            if b.get("name") == "submit_answer" and "resumed after idle" in b.get("arguments", "")
        ]
        assert len(idled) == 1
        assert len(resumed) == 1

        idle_child_task = bus.task(run_dir / "tasks" / "idle-child")
        idle_child_agent = bus.newest_agent(idle_child_task.id)
        last_request = json.loads(model.requests[-1])
        idle_results = [
            m
            for m in last_request["messages"]
            if m.get("role") == "tool" and m.get("tool_call_id") == "i1"
        ]
        assert len(idle_results) == 1
        assert idle_results[0]["content"].startswith(
            f"idling until one of agents [{idle_child_agent}] finishes"
        )
    finally:
        model.close()
