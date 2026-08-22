# Starts a run: writes the root task, then supervises it to completion.
import argparse
import logging
import pathlib
import sys

import pydantic

from ancalagon.answer_command import answer_command
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.clock import Clock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.env.real_environment import RealEnvironment
from ancalagon.fs.file_system import FileSystem
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrate_command import migrate_command
from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.sandbox.strategy import Strategy
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor

LOGGER = logging.getLogger(__name__)


def _allocated_run_dir(
    write_root: pathlib.PurePath, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    runs = write_root / "runs"
    fs.mkdir(runs, parents=True, exist_ok=True)
    return runs / clock.now().strftime("r_%Y%m%d-%H%M%S")


def created_run_dir(
    run_dir: str, write_root: pathlib.PurePath, clock: Clock, fs: FileSystem
) -> pathlib.PurePath:
    if run_dir:
        named = pathlib.PurePath(run_dir)
        fs.mkdir(named, parents=True, exist_ok=True)
        return named
    allocated = _allocated_run_dir(write_root, clock, fs)
    fs.mkdir(allocated, parents=True)
    return allocated


def init_command(config_path: pathlib.PurePath, run_dir: str) -> int:
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    sys.stdout.write(f"{created_run_dir(run_dir, config.write_root, SystemClock(), fs)}\n")
    return 0


def _text_of(path: pathlib.PurePath, named_by: str, fs: FileSystem) -> str:
    if not fs.is_file(path):
        raise ValueError(f"[run] {named_by} names {path}, which does not exist")
    return fs.read_text(path)


def goal_of(settings: RunSettings, fs: FileSystem) -> str:
    if not settings.goal_file:
        raise ValueError("no goal: set [run] goal_file")
    goal = _text_of(pathlib.PurePath(settings.goal_file), "goal_file", fs)
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


def root_spec(config: Config, fs: FileSystem) -> AgentSpec[pydantic.BaseModel]:
    if config.run.role not in config.roles:
        raise ValueError(
            f"[run] role: no role named {config.run.role}; declared: {sorted(config.roles)}"
        )
    role = config.roles[config.run.role]
    goal = goal_of(config.run, fs)
    input_class = resolve_class(role.input)
    given = (
        input_class.model_validate_json(
            _text_of(pathlib.PurePath(config.run.input_file), "input_file", fs)
        )
        if config.run.input_file
        else _from_goal(input_class, role, goal)
    )
    return AgentSpec[input_class](task_id="root", role=role, goal=goal, input=given)


def sandbox_of(config: Config, run_dir: pathlib.PurePath, fs: FileSystem) -> Sandbox:
    if config.sandbox is Strategy.NONE:
        return Unsandboxed()
    return Fence(
        write_root=config.write_root,
        allowed_domains=config.allowed_domains,
        run_dir=run_dir,
        fs=fs,
    )


def main(config_path: pathlib.PurePath, run_dir: pathlib.PurePath) -> int:
    logging.basicConfig(level=logging.INFO)
    fs = RealFileSystem()
    config = load_config(config_path, fs)
    check_contracts(config)

    clock = SystemClock()
    db = run_dir / "bus.db"
    bus = LifecycleStore.open(db, clock, fs)

    task_dir = run_dir / "tasks" / "root"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    fs.write_text(task_dir / "spec.json", root_spec(config, fs).model_dump_json())
    bus.enqueue(task_dir, parent_agent=HUMAN)
    supervisor = Supervisor(
        bus=LifecycleStore.open(db, clock, fs),
        spawner=SubprocessSpawner(
            run_dir=run_dir,
            config_path=fs.resolve(config_path),
            environment=RealEnvironment(),
            fs=fs,
            sandbox=sandbox_of(config, run_dir, fs),
        ),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
        clock=clock,
        fs=fs,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    task = bus.task(task_dir)
    newest = newest_agent(bus.snapshot(), task.id)
    outcome = task_dir / f"outcome-{newest}.json"
    if not fs.exists(outcome):
        LOGGER.error("root task produced no outcome; see %s", task_dir)
        return 1
    sys.stdout.write(fs.read_text(outcome) + "\n")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(prog="ancalagon")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=pathlib.PurePath, required=True)
    run.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    init = commands.add_parser("init")
    init.add_argument("--config", type=pathlib.PurePath, required=True)
    init.add_argument("--run-dir", type=str, default="")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--db", type=pathlib.PurePath, required=True)
    migrate.add_argument("--to", type=int, default=-1)
    answer = commands.add_parser("answer")
    answer.add_argument("--run-dir", type=pathlib.PurePath, required=True)
    answer.add_argument("--task", type=int, required=True)
    answer.add_argument("--answer", type=str, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            return init_command(args.config, args.run_dir)
        if args.command == "migrate":
            return migrate_command(args.db, args.to, RealFileSystem())
        if args.command == "answer":
            return answer_command(args.run_dir, args.task, args.answer)
        return main(args.config, args.run_dir)
    except ValueError as error:
        sys.stderr.write(f"{error}\n")
        return 2


if __name__ == "__main__":
    sys.exit(cli())
