# Starts a run: writes the root task, then supervises it to completion.
import argparse
import ast
import json
import logging
import pathlib
import sys

from ancalagon.bus.bus import Bus
from ancalagon.config.load import load_config
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.migrate_command import migrate_command
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor

LOGGER = logging.getLogger(__name__)

FREE_TEXT_OUTPUT = "contracts.py:FreeText"


def _allocated_run_dir(write_root: pathlib.Path) -> pathlib.Path:
    runs = write_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name[2:]) for p in runs.glob("r_*") if p.name[2:].isdigit()]
    return runs / f"r_{max(existing, default=0) + 1:04d}"


def run_dir_of(settings: RunSettings, write_root: pathlib.Path) -> pathlib.Path:
    if settings.run_dir:
        named = pathlib.Path(settings.run_dir)
        named.mkdir(parents=True, exist_ok=True)
        return named
    allocated = _allocated_run_dir(write_root)
    allocated.mkdir(parents=True)
    return allocated


def _text_of(path: pathlib.Path, named_by: str) -> str:
    if not path.is_file():
        raise ValueError(f"[run] {named_by} names {path}, which does not exist")
    return path.read_text()


def goal_of(settings: RunSettings, given: str) -> str:
    if settings.goal_file and given:
        raise ValueError("a goal came from both --goal and [run] goal_file; give one")
    if settings.goal_file:
        goal = _text_of(pathlib.Path(settings.goal_file), "goal_file")
        if not goal.strip():
            raise ValueError(f"[run] goal_file {settings.goal_file} is empty")
        return goal
    if given:
        return given
    raise ValueError("no goal: pass --goal or set [run] goal_file")


def output_of(settings: RunSettings) -> str:
    if not settings.contract_class:
        return FREE_TEXT_OUTPUT
    return f"contracts.py:{settings.contract_class}"


def _class_names(source: str, path: str) -> frozenset[str]:
    try:
        parsed = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"[run] contract module {path} does not parse: {error}") from error
    return frozenset(node.name for node in parsed.body if isinstance(node, ast.ClassDef))


def contract_source(settings: RunSettings) -> str:
    if not settings.contract_module:
        return FREE_TEXT_MODULE
    source = _text_of(pathlib.Path(settings.contract_module), "contract")
    if settings.contract_class not in _class_names(source, settings.contract_module):
        raise ValueError(
            f"[run] contract module {settings.contract_module} defines no class "
            f"{settings.contract_class}"
        )
    return source


def main(config_path: pathlib.Path, goal_argument: str) -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config(config_path)
    goal = goal_of(config.run, goal_argument)
    run_dir = run_dir_of(config.run, config.write_root)
    task_dir = run_dir / "tasks" / "root"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "contracts.py").write_text(contract_source(config.run))
    (task_dir / "spec.json").write_text(
        json.dumps(
            {
                "task_id": "root",
                "behaviour": config.root_behaviour,
                "goal": goal,
                "input": {"text": goal},
                "output": output_of(config.run),
                "budget": {
                    "turns": config.budget.turns,
                    "tool_calls": config.budget.tool_calls,
                },
                "tools": [],
            }
        )
    )

    outcome = task_dir / "outcome.json"
    outcome.unlink(missing_ok=True)

    db = run_dir / "bus.db"
    bus = Bus.open(db) if db.exists() else Bus.create(db)
    bus.enqueue(task_dir, parent_agent=0)
    supervisor = Supervisor(
        bus=Bus.open(db),
        spawner=SubprocessSpawner(run_dir=run_dir, config_path=config_path.resolve()),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    if not outcome.exists():
        LOGGER.error("root task produced no outcome; see %s", task_dir)
        return 1
    sys.stdout.write(outcome.read_text() + "\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=pathlib.Path, required=True)
    run.add_argument("--goal", type=str, default="")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--db", type=pathlib.Path, required=True)
    migrate.add_argument("--to", type=int, default=-1)
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            return migrate_command(args.db, args.to)
        return main(args.config, args.goal)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
