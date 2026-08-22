import json
import os
import pathlib
import subprocess
import sys

import pytest

from ancalagon.attempt.closed import Closed
from ancalagon.attempt.lost import Lost
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.cli import main
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.schedule.task_of import task_of
from tests.integration.prepared_run import prepared_run_dir
from ancalagon.supervisor.process import Process
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner

ROOT_BEHAVIOUR = (
    "You investigate a codebase or a set of artifacts to answer the goal you are given."
)


def _config(
    tmp_path: pathlib.Path,
    turns: int,
    tool_calls: int,
    model: str = "",
    goal: str = "",
    goal_file: str = "",
    input_file: str = "",
    input_module: str = "",
    input_class: str = "",
    role_name: str = "root",
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
    input_line = (
        f'input = {{ module = "{input_module}", name = "{input_class}" }}\n' if input_module else ""
    )
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{artifacts}"]

[model]
name = "{model}"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "none"

[roles.{role_name}]
behaviour = "{ROOT_BEHAVIOUR}"
{input_line}tools = ["read_file"]

[roles.{role_name}.budget]
turns = {turns}
tool_calls = {tool_calls}

[run]
goal_file = "{goal_source}"
input_file = "{input_file}"
role = "{role_name}"
""")
    return config


def _cli(env: dict[str, str], *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ancalagon.cli", *argv],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )


def _run_cli(
    config: pathlib.Path, env: dict[str, str], run_dir: str = ""
) -> subprocess.CompletedProcess[str]:
    named = ["--run-dir", run_dir] if run_dir else []
    started = _cli(env, "init", "--config", str(config), *named)
    assert started.returncode == 0, started.stderr
    allocated = started.stdout.strip()
    migrated = _cli(env, "migrate", "--db", f"{allocated}/bus.db")
    assert migrated.returncode == 0, migrated.stderr
    return _cli(env, "run", "--config", str(config), "--run-dir", allocated)


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
    assert json.loads((task_dir / "spec.json").read_text())["role"]["behaviour"] == ROOT_BEHAVIOUR

    outcome = json.loads((task_dir / "outcome-1.json").read_text())
    assert outcome["kind"] == "failed"
    assert outcome["error"] != ""

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())
    assert bus.attempt(1) == Closed(verdict=AgentStatus.FAILED)

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
        goal="Say hello.",
    )

    first = _run_cli(config, dict(os.environ), run_dir=str(named))
    assert first.returncode == 0, first.stderr
    second = _run_cli(config, dict(os.environ), run_dir=str(named))
    assert second.returncode == 0, second.stderr

    assert [p.name for p in (tmp_path / "ws" / "runs").iterdir()] == ["item-0001"]

    bus = LifecycleStore.open(named / "bus.db", SystemClock())
    task = bus.task(named / "tasks" / "root")
    snapshot = bus.snapshot()
    assert task_of(snapshot, 1).id == task.id
    assert task_of(snapshot, 2).id == task.id
    assert bus.attempt(1) == Closed(verdict=AgentStatus.FAILED)
    assert bus.attempt(2) == Closed(verdict=AgentStatus.FAILED)
    assert len(list((named / "tasks" / "root").glob("stderr-*.log"))) == 2


QUERY_MODULE = "import pydantic\n\n\nclass Query(pydantic.BaseModel):\n    area: str\n"


def _case(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    case = tmp_path / name
    case.mkdir()
    (case / "goal.md").write_text("describe the item")
    return case


def test_a_missing_or_unusable_input_exits_two_with_a_message_and_no_traceback(
    tmp_path: pathlib.Path,
):
    def failed(case: pathlib.Path, **run_kwargs: str) -> subprocess.CompletedProcess[str]:
        config = _config(case, turns=1, tool_calls=1, model="m", **run_kwargs)
        completed = _run_cli(config, dict(os.environ))
        assert completed.returncode == 2, completed.stdout
        assert "Traceback" not in completed.stderr
        return completed

    absent = _case(tmp_path, "absent-goal")
    assert "no-such-goal.md" in failed(absent, goal_file=str(absent / "no-such-goal.md")).stderr

    blank = _case(tmp_path, "blank-goal")
    (blank / "goal.md").write_text("   \n")
    assert "empty" in failed(blank, goal_file=str(blank / "goal.md")).stderr

    gone = _case(tmp_path, "absent-input-file")
    missing = failed(
        gone, goal_file=str(gone / "goal.md"), input_file=str(gone / "no-such-input.json")
    )
    assert "no-such-input.json" in missing.stderr

    unnamed = _case(tmp_path, "unknown-role")
    config = _config(unnamed, turns=1, tool_calls=1, model="m", goal_file=str(unnamed / "goal.md"))
    config.write_text(config.read_text().replace('role = "root"', 'role = "ghost"'))
    completed = _run_cli(config, dict(os.environ))
    assert completed.returncode == 2, completed.stdout
    assert "Traceback" not in completed.stderr
    assert "no role named ghost" in completed.stderr

    unparsable = tmp_path / "unparsable.py"
    unparsable.write_text("import pydantic\n\n\nclass Query(pydantic.BaseModel\n    area: str\n")
    broken = _case(tmp_path, "unparsable-contract")
    refused = failed(
        broken,
        goal_file=str(broken / "goal.md"),
        input_module=str(unparsable),
        input_class="Query",
    )
    assert "[roles.root] input" in refused.stderr
    assert str(unparsable) in refused.stderr
    assert "SyntaxError" in refused.stderr

    absent_module = tmp_path / "no-such-shapes.py"
    nowhere = _case(tmp_path, "absent-contract-module")
    unloadable = failed(
        nowhere,
        goal_file=str(nowhere / "goal.md"),
        input_module=str(absent_module),
        input_class="Query",
    )
    assert "[roles.root] input" in unloadable.stderr
    assert str(absent_module) in unloadable.stderr

    shapes = tmp_path / "shapes.py"
    shapes.write_text(QUERY_MODULE)
    structured = _case(tmp_path, "structured-without-input")
    incomplete = failed(
        structured,
        goal_file=str(structured / "goal.md"),
        input_module=str(shapes),
        input_class="Query",
    )
    assert "area" in incomplete.stderr


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
        goal="Say hello.",
    )
    task_dir = named / "tasks" / "root"

    assert main(config, prepared_run_dir(named)) == 0
    opened = LifecycleStore.open(named / "bus.db", SystemClock())
    task = opened.task(task_dir)
    first_agent = newest_agent(opened.snapshot(), task.id)
    first_outcome = task_dir / f"outcome-{first_agent}.json"
    assert json.loads(first_outcome.read_text())["kind"] == "failed"
    capsys.readouterr()

    def refuse(self: SubprocessSpawner, task_dir: pathlib.Path, agent_id: int) -> Process:
        raise OSError("no process could be started")

    monkeypatch.setattr(SubprocessSpawner, "spawn", refuse)

    assert main(config, named) == 1
    assert capsys.readouterr().out == ""
    second_agent = newest_agent(opened.snapshot(), task.id)
    assert second_agent != first_agent
    assert (task_dir / f"outcome-{second_agent}.json").exists() is False
    assert first_outcome.exists() is True

    def crash(self: SubprocessSpawner, task_dir: pathlib.Path, agent_id: int) -> Process:
        return subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])

    monkeypatch.setattr(SubprocessSpawner, "spawn", crash)

    assert main(config, named) == 1
    assert capsys.readouterr().out == ""
    third_agent = newest_agent(opened.snapshot(), task.id)
    assert third_agent != second_agent
    assert (task_dir / f"outcome-{third_agent}.json").exists() is False
    assert first_outcome.exists() is True

    bus = LifecycleStore.open(named / "bus.db", SystemClock())
    assert bus.attempt(newest_agent(bus.snapshot(), task.id)) == Lost(close=AgentStatus.CRASHED)


def test_a_run_refuses_a_database_the_startup_script_has_not_migrated(tmp_path: pathlib.Path):
    named = tmp_path / "ws" / "runs" / "item-0001"
    config = _config(
        tmp_path,
        turns=2,
        tool_calls=4,
        model="no-such-provider/no-such-model",
        goal="Say hello.",
    )
    named.mkdir(parents=True)

    with pytest.raises(ValueError, match="ancalagon migrate"):
        main(config, named)
    assert (named / "bus.db").exists() is False

    migrate_file(named / "bus.db", 0)
    with pytest.raises(ValueError, match="schema version 0, not 1"):
        main(config, named)

    migrate_file(named / "bus.db", latest_version())
    assert main(config, named) == 0
