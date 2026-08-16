import json
import os
import pathlib
import subprocess
import sys

import pytest

from ancalagon.bus.bus import Bus
from ancalagon.clock.system_clock import SystemClock
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.cli import main
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner


def _config(
    tmp_path: pathlib.Path,
    turns: int,
    tool_calls: int,
    model: str = "",
    run_dir: str = "",
    goal: str = "",
    goal_file: str = "",
    contract_module: str = "",
    contract_class: str = "",
) -> pathlib.Path:
    model = model or os.environ.get("ANCALAGON_MODEL", "claude-opus-5")
    write_root = tmp_path / "ws"
    artifacts = tmp_path / "artifacts"
    write_root.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "a", "body": "reads a file"},
                    {"id": "b", "body": "writes a file"},
                ]
            }
        )
    )
    written = tmp_path / "goal.md"
    if goal:
        written.write_text(goal)
    goal_source = str(written) if goal else goal_file
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{artifacts}"]

[agent]
root_behaviour = "You investigate."

[model]
name = "{model}"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[budget]
turns = {turns}
tool_calls = {tool_calls}

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[tools]
enabled = []

[sandbox]
strategy = "none"

[run]
run_dir = "{run_dir}"
goal_file = "{goal_source}"
contract_module = "{contract_module}"
contract_class = "{contract_class}"
""")
    return config


def _run_cli(config: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ancalagon.cli", "run", "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )


def test_pipeline_spawns_a_worker_and_records_its_failure_without_a_model(
    tmp_path: pathlib.Path,
):
    config = _config(
        tmp_path,
        turns=2,
        tool_calls=4,
        model="no-such-provider/no-such-model",
        goal="Say hello.",
    )

    completed = _run_cli(config, dict(os.environ))
    assert completed.returncode == 0, completed.stderr

    run_dir = next((tmp_path / "ws" / "runs").iterdir())
    task_dir = run_dir / "tasks" / "root"

    assert (run_dir / "bus.db").exists()
    assert (task_dir / "spec.json").exists()
    assert (task_dir / "free_text.py").exists()

    outcome = json.loads((task_dir / "outcome.json").read_text())
    assert outcome["kind"] == "failed"
    assert outcome["error"] != ""

    bus = Bus.open(run_dir / "bus.db", SystemClock())
    row = bus.state(1)
    assert row.status is AgentStatus.CRASHED
    assert row.exit_code == 1
    assert bus.live() == []

    stderr_logs = list(task_dir.glob("stderr-*.log"))
    assert len(stderr_logs) == 1
    assert "worker failed" in stderr_logs[0].read_text()


@pytest.mark.skipif(
    os.environ.get("ANCALAGON_LIVE") != "1",
    reason="live model test; set ANCALAGON_LIVE=1 with a funded credential to run",
)
def test_root_agent_investigates_and_returns_an_outcome(tmp_path: pathlib.Path):
    artifacts = tmp_path / "artifacts"
    config = _config(
        tmp_path,
        turns=8,
        tool_calls=20,
        goal=f"Read {artifacts / 'graph.json'} and state in one sentence what node 'a' does.",
    )

    completed = _run_cli(config, dict(os.environ))
    assert completed.returncode == 0, completed.stderr

    outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    assert outcome["kind"] in ("completed", "exhausted")
    assert "file" in outcome["value"]["text"].lower()

    run_dir = next((tmp_path / "ws" / "runs").iterdir())
    transcript = (run_dir / "tasks" / "root" / "transcript.jsonl").read_text()
    assert transcript.count("\n") >= 2


def test_a_named_run_dir_is_reused_by_a_second_invocation(tmp_path: pathlib.Path):
    named = tmp_path / "ws" / "runs" / "item-0001"
    config = _config(
        tmp_path,
        turns=2,
        tool_calls=4,
        model="no-such-provider/no-such-model",
        run_dir=str(named),
        goal="Say hello.",
    )

    first = _run_cli(config, dict(os.environ))
    assert first.returncode == 0, first.stderr
    second = _run_cli(config, dict(os.environ))
    assert second.returncode == 0, second.stderr

    assert [p.name for p in (tmp_path / "ws" / "runs").iterdir()] == ["item-0001"]

    bus = Bus.open(named / "bus.db", SystemClock())
    task = bus.task(named / "tasks" / "root")
    assert bus.state(1).task == task.id
    assert bus.state(2).task == task.id
    assert bus.state(1).status is AgentStatus.CRASHED
    assert bus.state(2).status is AgentStatus.CRASHED
    assert len(list((named / "tasks" / "root").glob("stderr-*.log"))) == 2


ANSWER_MODULE = "import pydantic\n\n\nclass Answer(pydantic.BaseModel):\n    verdict: str\n"


def _case(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    case = tmp_path / name
    case.mkdir()
    (case / "goal.md").write_text("describe the item")
    return case


def test_a_missing_or_unusable_input_exits_two_with_a_message_and_no_traceback(
    tmp_path: pathlib.Path,
):
    def failed(
        case: pathlib.Path, goal_file: str, contract_module: str, contract_class: str
    ) -> subprocess.CompletedProcess[str]:
        config = _config(
            case,
            turns=1,
            tool_calls=1,
            model="m",
            goal_file=goal_file,
            contract_module=contract_module,
            contract_class=contract_class,
        )
        completed = _run_cli(config, dict(os.environ))
        assert completed.returncode == 2, completed.stdout
        assert "Traceback" not in completed.stderr
        return completed

    absent = _case(tmp_path, "absent-goal")
    assert "no-such-goal.md" in failed(absent, str(absent / "no-such-goal.md"), "", "").stderr

    blank = _case(tmp_path, "blank-goal")
    (blank / "goal.md").write_text("   \n")
    assert "empty" in failed(blank, str(blank / "goal.md"), "", "").stderr

    gone = _case(tmp_path, "absent-contract")
    missing = failed(gone, str(gone / "goal.md"), str(gone / "no-such-shape.py"), "Answer")
    assert "no-such-shape.py" in missing.stderr

    typo = _case(tmp_path, "misspelt-class")
    (typo / "shape.py").write_text(ANSWER_MODULE)
    assert "Answr" in failed(typo, str(typo / "goal.md"), str(typo / "shape.py"), "Answr").stderr

    broken = _case(tmp_path, "unparsable-contract")
    (broken / "shape.py").write_text("class Answer(:\n")
    stderr = failed(broken, str(broken / "goal.md"), str(broken / "shape.py"), "Answer").stderr
    assert "does not parse" in stderr


def test_an_attempt_that_writes_no_outcome_never_reports_the_previous_one(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    named = tmp_path / "ws" / "runs" / "item-0001"
    config = _config(
        tmp_path,
        turns=2,
        tool_calls=4,
        model="no-such-provider/no-such-model",
        run_dir=str(named),
        goal="Say hello.",
    )
    outcome = named / "tasks" / "root" / "outcome.json"

    assert main(config) == 0
    assert json.loads(outcome.read_text())["kind"] == "failed"
    capsys.readouterr()

    def refuse(self: SubprocessSpawner, task_dir: pathlib.Path, agent_id: int) -> Process:
        raise OSError("no process could be started")

    monkeypatch.setattr(SubprocessSpawner, "spawn", refuse)

    assert main(config) == 1
    assert capsys.readouterr().out == ""
    assert outcome.exists() is False
