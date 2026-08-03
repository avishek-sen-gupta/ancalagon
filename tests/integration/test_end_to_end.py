import json
import os
import pathlib
import subprocess
import sys

import pytest

from ancalagon.bus.bus import Bus
from ancalagon.bus.task_status import TaskStatus


def _config(tmp_path: pathlib.Path, turns: int, tool_calls: int, model: str = "") -> pathlib.Path:
    model = model or os.environ.get("ANCALAGON_MODEL", "claude-opus-5")
    write_root = tmp_path / "ws"
    artifacts = tmp_path / "artifacts"
    write_root.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
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
    config = tmp_path / "ancalagon.toml"
    config.write_text(f"""
[workspace]
write_root = "{write_root}"
read_roots = ["{artifacts}"]

[model]
name = "{model}"
max_tokens = 4000

[budget]
turns = {turns}
tool_calls = {tool_calls}

[limits]
max_concurrent_agents = 1
agent_timeout_s = 300
max_depth = 1
summary_chars = 1000

[tools]
enabled = []
""")
    return config


def _run_cli(
    config: pathlib.Path, goal: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ancalagon.cli", "run", "--config", str(config), "--goal", goal],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )


def test_pipeline_spawns_a_worker_and_records_its_failure_without_a_model(
    tmp_path: pathlib.Path,
):
    config = _config(tmp_path, turns=2, tool_calls=4, model="no-such-provider/no-such-model")

    completed = _run_cli(config, "Say hello.", dict(os.environ))
    assert completed.returncode == 0, completed.stderr

    run_dir = next((tmp_path / "ws" / "runs").iterdir())
    task_dir = run_dir / "tasks" / "root"

    assert (run_dir / "bus.db").exists()
    assert (task_dir / "spec.json").exists()
    assert (task_dir / "contracts.py").exists()

    outcome = json.loads((task_dir / "outcome.json").read_text())
    assert outcome["kind"] == "failed"
    assert outcome["error"] != ""

    bus = Bus.open(run_dir / "bus.db")
    row = bus.get(1)
    assert row.status is TaskStatus.CRASHED
    assert row.exit_code == 1
    assert row.finished != ""
    assert bus.running() == []
    assert [m.kind for m in bus.inbox(consumer=0)] == ["task_done"]

    stderr_logs = list(task_dir.glob("stderr-*.log"))
    assert len(stderr_logs) == 1
    assert "worker failed" in stderr_logs[0].read_text()


@pytest.mark.skipif(
    os.environ.get("ANCALAGON_LIVE") != "1",
    reason="live model test; set ANCALAGON_LIVE=1 with a funded credential to run",
)
def test_root_agent_investigates_and_returns_an_outcome(tmp_path: pathlib.Path):
    config = _config(tmp_path, turns=8, tool_calls=20)
    artifacts = tmp_path / "artifacts"

    completed = _run_cli(
        config,
        f"Read {artifacts / 'graph.json'} and state in one sentence what node 'a' does.",
        dict(os.environ),
    )
    assert completed.returncode == 0, completed.stderr

    outcome = json.loads(completed.stdout.strip().splitlines()[-1])
    assert outcome["kind"] in ("completed", "exhausted")
    assert "file" in outcome["value"]["text"].lower()

    run_dir = next((tmp_path / "ws" / "runs").iterdir())
    transcript = (run_dir / "tasks" / "root" / "transcript.jsonl").read_text()
    assert transcript.count("\n") >= 2
