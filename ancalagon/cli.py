import argparse
import json
import logging
import pathlib
import sys

from ancalagon.bus.bus import Bus
from ancalagon.config.load import load_config
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor

LOGGER = logging.getLogger(__name__)

ROOT_BEHAVIOUR = (
    "You are a reverse engineering agent. Use your tools to investigate, and delegate "
    "focused subtasks with the delegate tool when a question is self-contained."
)


def _new_run_dir(write_root: pathlib.Path) -> pathlib.Path:
    runs = write_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[2:]) for p in runs.glob("r_*") if p.name[2:].isdigit()]
    run_dir = runs / f"r_{max(existing, default=0) + 1:04d}"
    run_dir.mkdir()
    return run_dir


def main(config_path: pathlib.Path, goal: str) -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config(config_path)
    run_dir = _new_run_dir(config.write_root)
    task_dir = run_dir / "tasks" / "root"
    task_dir.mkdir(parents=True)
    (task_dir / "contracts.py").write_text(FREE_TEXT_MODULE)
    (task_dir / "spec.json").write_text(
        json.dumps(
            {
                "task_id": "root",
                "behaviour": ROOT_BEHAVIOUR,
                "goal": goal,
                "input": {"text": goal},
                "output": "contracts.py:FreeText",
                "budget": {
                    "turns": config.budget.turns,
                    "tool_calls": config.budget.tool_calls,
                },
                "tools": [],
            }
        )
    )

    bus = Bus.open(run_dir / "bus.db")
    bus.enqueue(task_dir, parent=0)
    supervisor = Supervisor(
        bus=Bus.open(run_dir / "bus.db"),
        spawner=SubprocessSpawner(run_dir=run_dir, config_path=config_path.resolve()),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    outcome = task_dir / "outcome.json"
    if not outcome.exists():
        LOGGER.error("root task produced no outcome; see %s", task_dir)
        return 1
    sys.stdout.write(outcome.read_text() + "\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--goal", type=str, required=True)
    args = parser.parse_args()
    return main(args.config, args.goal)


if __name__ == "__main__":
    sys.exit(cli())
