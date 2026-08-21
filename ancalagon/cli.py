# Starts a run: writes the root task, then supervises it to completion.
import argparse
import logging
import pathlib
import sys

import pydantic

import ancalagon.migrations
from ancalagon.answer_command import answer_command
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.migrate_command import migrate_command
from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.sandbox.strategy import Strategy
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor

LOGGER = logging.getLogger(__name__)


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


def goal_of(settings: RunSettings) -> str:
    if not settings.goal_file:
        raise ValueError("no goal: set [run] goal_file")
    goal = _text_of(pathlib.Path(settings.goal_file), "goal_file")
    if not goal.strip():
        raise ValueError(f"[run] goal_file {settings.goal_file} is empty")
    return goal


def _from_goal(input_class: type[pydantic.BaseModel], role: Role, goal: str) -> pydantic.BaseModel:
    try:
        return input_class.model_validate({"text": goal})
    except pydantic.ValidationError as error:
        raise ValueError(
            f"[run] input_file is unset, so root's input was built from the goal alone as "
            f"{{'text': goal}}; that does not satisfy {role.input.name}, the role's input "
            f"class: {error}"
        ) from error


def _contract_fault(name: str, field: str, ref: ClassRef) -> str:
    try:
        resolve_class(ref)
        return ""
    except Exception as error:
        return (
            f"[roles.{name}] {field} names {ref.name} in {ref.module}, "
            f"which cannot be loaded: {type(error).__name__}: {error}"
        )


def check_contracts(config: Config) -> None:
    faults = [
        fault
        for name, role in config.roles.items()
        for field, ref in (("input", role.input), ("answer", role.answer))
        if (fault := _contract_fault(name, field, ref))
    ]
    if faults:
        raise ValueError("\n".join(faults))


def root_spec(config: Config) -> AgentSpec[pydantic.BaseModel]:
    if config.run.role not in config.roles:
        raise ValueError(
            f"[run] role: no role named {config.run.role}; declared: {sorted(config.roles)}"
        )
    role = config.roles[config.run.role]
    goal = goal_of(config.run)
    input_class = resolve_class(role.input)
    given = (
        input_class.model_validate_json(_text_of(pathlib.Path(config.run.input_file), "input_file"))
        if config.run.input_file
        else _from_goal(input_class, role, goal)
    )
    return AgentSpec[input_class](task_id="root", role=role, goal=goal, input=given)


def sandbox_of(config: Config, run_dir: pathlib.Path) -> Sandbox:
    if config.sandbox is Strategy.NONE:
        return Unsandboxed()
    return Fence(
        write_root=config.write_root,
        allowed_domains=config.allowed_domains,
        run_dir=run_dir,
    )


def main(config_path: pathlib.Path) -> int:
    logging.basicConfig(level=logging.INFO)
    config = load_config(config_path)
    check_contracts(config)
    run_dir = run_dir_of(config.run, config.write_root)
    task_dir = run_dir / "tasks" / "root"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "spec.json").write_text(root_spec(config).model_dump_json())

    clock = SystemClock()
    db = run_dir / "bus.db"
    ancalagon.migrations.migrate_file(db, ancalagon.migrations.latest_version())
    bus = LifecycleStore.open(db, clock)
    bus.enqueue(task_dir, parent_agent=HUMAN)
    supervisor = Supervisor(
        bus=LifecycleStore.open(db, clock),
        spawner=SubprocessSpawner(
            run_dir=run_dir,
            config_path=config_path.resolve(),
            sandbox=sandbox_of(config, run_dir),
        ),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
        clock=clock,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    task = bus.task(task_dir)
    newest = newest_agent(bus.snapshot(), task.id)
    outcome = task_dir / f"outcome-{newest}.json"
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
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--db", type=pathlib.Path, required=True)
    migrate.add_argument("--to", type=int, default=-1)
    answer = commands.add_parser("answer")
    answer.add_argument("--run-dir", type=pathlib.Path, required=True)
    answer.add_argument("--task", type=int, required=True)
    answer.add_argument("--answer", type=str, required=True)
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            return migrate_command(args.db, args.to)
        if args.command == "answer":
            return answer_command(args.run_dir, args.task, args.answer)
        return main(args.config)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
