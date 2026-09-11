# Starts a run: writes the root task, then supervises it to completion.
import pathlib

import pydantic

from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.check_contracts import check_contracts
from ancalagon.clock.clock import Clock
from ancalagon.config.config import Config
from ancalagon.config.on_path import on_path
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.no_outcome import NoOutcome
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.run_settings import RunSettings
from ancalagon.env.real_environment import RealEnvironment
from ancalagon.fs.file_system import FileSystem
from ancalagon.sandbox.fence import Fence
from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.sandbox.strategy import Strategy
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.supervisor.spawn_by_run import SpawnByRun
from ancalagon.supervisor.spawner import Spawner
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor

CONFIG = "config.json"


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
        allowed_domains=config.allowed_domains + config.web_domains,
        run_dir=run_dir,
        fs=fs,
    )


def _spawner(config: Config, run_dir: pathlib.PurePath, fs: FileSystem) -> Spawner:
    sandbox = sandbox_of(config, run_dir, fs)
    ordinary = SubprocessSpawner(
        run_dir=run_dir,
        config_path=run_dir / CONFIG,
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.worker",
        sandbox=sandbox,
    )
    deterministic = SubprocessSpawner(
        run_dir=run_dir,
        config_path=run_dir / CONFIG,
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.deterministic.run",
        sandbox=sandbox,
    )
    return SpawnByRun(default=ordinary, deterministic=deterministic, fs=fs)


def _outcome_of(
    config: Config, task_dir: pathlib.PurePath, bus: LifecycleStore, fs: FileSystem
) -> Outcome[pydantic.BaseModel]:
    task = bus.task(task_dir)
    newest = newest_agent(bus.snapshot(), task.id)
    written = task_dir / f"outcome-{newest}.json"
    if not fs.exists(written):
        raise NoOutcome(task_dir)
    answer = resolve_class(config.roles[config.run.role].answer)
    adapter: pydantic.TypeAdapter[Outcome[pydantic.BaseModel]] = pydantic.TypeAdapter(
        Outcome[answer]
    )
    return adapter.validate_json(fs.read_text(written))


def run(
    config: Config,
    run_dir: pathlib.PurePath,
    clock: Clock,
    fs: FileSystem,
) -> Outcome[pydantic.BaseModel]:
    on_path(config.import_paths)
    check_contracts(config, fs)
    fs.mkdir(run_dir, parents=True, exist_ok=True)
    fs.write_text(run_dir / CONFIG, config.model_dump_json())
    task_dir = run_dir / "tasks" / "root"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    fs.write_text(task_dir / "spec.json", root_spec(config, fs).model_dump_json())
    db = run_dir / "bus.db"
    bus = LifecycleStore.open(db, clock, fs)
    bus.enqueue(task_dir, parent_agent=HUMAN)
    supervisor = Supervisor(
        bus=LifecycleStore.open(db, clock, fs),
        spawner=_spawner(config, run_dir, fs),
        max_concurrent=config.max_concurrent_agents,
        timeout_s=config.agent_timeout_s,
        clock=clock,
        fs=fs,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()
    return _outcome_of(config, task_dir, bus, fs)
