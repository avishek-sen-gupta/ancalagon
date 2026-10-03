import json
import os
import pathlib
import subprocess
import sys

from ancalagon.attempt.closed import Closed
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.fs.real_file_system import RealFileSystem

BEHAVIOUR = "You answer the question you are given."


def _document(base: pathlib.Path) -> str:
    return json.dumps(
        {
            "base": str(base),
            "workspace": {
                "home": "./ws",
                "write_roots": [],
                "read_roots": ["./artifacts"],
            },
            "model": {
                "name": "no-such-provider/no-such-model",
                "num_retries": 1,
                "request_timeout_s": 30,
                "max_tokens": 1000,
                "allowed_domains": [],
            },
            "limits": {
                "max_concurrent_agents": 1,
                "agent_timeout_s": 120,
                "max_depth": 0,
                "compact_above_tokens": 60000,
                "keep_recent_messages": 8,
                "summary_chars": 1000,
            },
            "sandbox": {"strategy": "none"},
            "roles": {
                "root": {
                    "behaviour": BEHAVIOUR,
                    "profile": {
                        "module": "ancalagon.profiles.answering",
                        "name": "Answering",
                    },
                    "tools": ["read_file", "submit_answer"],
                    "budget": {"turns": 2, "tool_calls": 4},
                }
            },
            "run": {"goal_file": "./goal.md", "input_file": "", "role": "root"},
        }
    )


def _cli(document: str, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ancalagon.cli", *argv],
        input=document,
        capture_output=True,
        text=True,
        timeout=300,
        env=dict(os.environ),
    )


def test_a_run_is_driven_entirely_from_a_document_on_stdin(tmp_path: pathlib.Path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "goal.md").write_text("Say hello.")
    document = _document(tmp_path)

    started = _cli(document, "init", "--config-json")
    assert started.returncode == 0, started.stderr
    allocated = started.stdout.strip()

    migrated = _cli("", "migrate", "--db", f"{allocated}/bus.db")
    assert migrated.returncode == 0, migrated.stderr

    completed = _cli(document, "run", "--config-json", "--run-dir", allocated)
    assert completed.returncode == 0, completed.stderr

    assert list((tmp_path / "ws" / "runs").iterdir()) == [pathlib.Path(allocated)]
    task_dir = pathlib.Path(allocated) / "tasks" / "root"
    assert json.loads((task_dir / "spec.json").read_text())["role"]["behaviour"] == BEHAVIOUR

    outcome = json.loads((task_dir / "outcome-1.json").read_text())
    assert outcome["kind"] == "failed"

    bus = LifecycleStore.open(pathlib.Path(allocated) / "bus.db", SystemClock(), RealFileSystem())
    assert bus.attempt(1) == Closed(verdict=AgentStatus.FAILED)


def test_a_run_dir_allocated_from_one_document_is_reused_by_the_next_spawn(
    tmp_path: pathlib.Path,
):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "goal.md").write_text("Say hello.")
    document = _document(tmp_path)

    first = _cli(document, "init", "--config-json")
    assert first.returncode == 0, first.stderr
    second = _cli(document, "init", "--config-json", "--run-dir", first.stdout.strip())

    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == first.stdout.strip()
