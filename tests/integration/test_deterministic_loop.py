import collections.abc
import importlib
import json
import pathlib

import pydantic

from ancalagon.attempt.collected import Collected
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.load import load_config
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.finite import Finite
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.role import Role
from ancalagon.env.real_environment import RealEnvironment
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.supervisor.spawn_by_run import SpawnByRun
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor
from tests.integration.prepared_run import prepared_run_dir

ROUNDS = 5

LOOPKIT = """
import pydantic

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.nothing import NOTHING
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.role import Role
from ancalagon.deterministic.run_context import RunContext
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.contracts.finite import Finite

MODULE = "loopkit.rounds"
COUNTER = "rounds"


class Rounds(pydantic.BaseModel, frozen=True):
    total: int


class Tick(pydantic.BaseModel, frozen=True):
    n: int


class Ticks(pydantic.BaseModel, frozen=True):
    ns: tuple[int, ...]


def child(tick: Tick, ctx: RunContext) -> Outcome[Tick]:
    return Completed(value=tick, summary=f"tick {tick.n}", spent=NOTHING)


def _spawn(n: int, ctx: RunContext) -> int:
    child_dir = ctx.run_dir / "tasks" / f"tick-{n}"
    ctx.fs.mkdir(child_dir, parents=True, exist_ok=True)
    spec = AgentSpec[Tick](
        task_id=child_dir.name,
        role=Role(
            behaviour="Tick once.",
            run=FunctionRef(module=MODULE, name="child"),
            input=ClassRef(module=MODULE, name="Tick"),
            answer=ClassRef(module=MODULE, name="Tick"),
            tools=(),
            budget=Budget(turns=Finite(value=0), tool_calls=Finite(value=0)),
        ),
        goal=f"Tick {n}.",
        input=Tick(n=n),
    )
    ctx.fs.write_text(child_dir / "spec.json", spec.model_dump_json())
    bus = LifecycleStore.open(ctx.run_dir / "bus.db", ctx.clock, ctx.fs)
    snapshot = bus.snapshot()
    seen = max((e.id for events in snapshot.events.values() for e in events), default=0)
    bus.enqueue(child_dir, parent_agent=ctx.agent_id)
    return seen


def _answer(n: int, ctx: RunContext) -> Tick:
    child_dir = ctx.run_dir / "tasks" / f"tick-{n}"
    written = ctx.fs.glob(child_dir, "outcome-*.json")[0]
    outcome = pydantic.TypeAdapter(Outcome[Tick]).validate_json(ctx.fs.read_text(written))
    assert isinstance(outcome, Completed)
    return outcome.value


def _collect(n: int, ctx: RunContext) -> None:
    bus = LifecycleStore.open(ctx.run_dir / "bus.db", ctx.clock, ctx.fs)
    task = bus.task(ctx.run_dir / "tasks" / f"tick-{n}")
    bus.record(newest_agent(bus.snapshot(), task.id), AgentStatus.COLLECTED, EventSource.WORKER)


def parent(rounds: Rounds, ctx: RunContext) -> Outcome[Ticks]:
    counter = ctx.task_dir / COUNTER
    done = int(ctx.fs.read_text(counter)) if ctx.fs.exists(counter) else 0
    if done:
        _collect(done, ctx)
    if done == rounds.total:
        ns = tuple(_answer(n, ctx).n for n in range(1, done + 1))
        return Completed(value=Ticks(ns=ns), summary=f"collected {list(ns)}", spent=NOTHING)
    ctx.fs.write_text(counter, str(done + 1))
    return Idling(
        summary=f"spawned tick {done + 1}", spent=NOTHING, seen_through=_spawn(done + 1, ctx)
    )
"""

CONFIG = """
[workspace]
write_root = "./ws"
read_roots = ["./ws"]

[model]
name = "some-provider/some-model"
num_retries = 2
request_timeout_s = 120
max_tokens = 4000
allowed_domains = []

[limits]
max_concurrent_agents = 2
agent_timeout_s = 300
max_depth = 1
compact_above_tokens = 60000
keep_recent_messages = 8
summary_chars = 1000

[sandbox]
strategy = "fence"

[roles.looper]
behaviour = "Spawn a child, wait for it, repeat."
run = { module = "loopkit.rounds", name = "parent" }
tools = []
budget = { turns = 0, tool_calls = 0 }

[run]
goal_file = ""
input_file = ""
role = "looper"
"""


def test_a_deterministic_parent_is_woken_once_per_child_it_spawns(
    tmp_path: pathlib.Path, importable: collections.abc.Callable[[pathlib.Path], None]
):
    fs = RealFileSystem()
    package = tmp_path / "loopkit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "rounds.py").write_text(LOOPKIT)
    importable(tmp_path)
    toml_path = tmp_path / "loop.toml"
    toml_path.write_text(CONFIG)
    config = load_config(pathlib.PurePath(toml_path), fs)
    config_path = tmp_path / "loop.json"
    config_path.write_text(config.model_dump_json())

    rounds_class: type[pydantic.BaseModel] = importlib.import_module("loopkit.rounds").Rounds
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "loop")
    task_dir = run_dir / "tasks" / "looper"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    given = rounds_class(total=ROUNDS)
    spec = AgentSpec[rounds_class](
        task_id="looper",
        role=Role(
            behaviour="Spawn a child, wait for it, repeat.",
            run=FunctionRef(module="loopkit.rounds", name="parent"),
            input=ClassRef(module="loopkit.rounds", name="Rounds"),
            answer=ClassRef(module="loopkit.rounds", name="Ticks"),
            tools=(),
            budget=Budget(turns=Finite(value=0), tool_calls=Finite(value=0)),
        ),
        goal=f"Spawn {ROUNDS} children, one at a time.",
        input=given,
    )
    fs.write_text(task_dir / "spec.json", spec.model_dump_json())

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs)
    bus.enqueue(task_dir, parent_agent=HUMAN)

    def spawner(module: str) -> SubprocessSpawner:
        return SubprocessSpawner(
            run_dir=run_dir,
            config_path=config_path,
            environment=RealEnvironment(),
            fs=fs,
            module=module,
            sandbox=Unsandboxed(),
        )

    supervisor = Supervisor(
        bus=LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs),
        spawner=SpawnByRun(
            default=spawner("ancalagon.worker"),
            deterministic=spawner("ancalagon.deterministic.run"),
            fs=fs,
        ),
        max_concurrent=2,
        timeout_s=60,
        clock=SystemClock(),
        fs=fs,
    )
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    assert (task_dir / "rounds").read_text() == str(ROUNDS)

    ticks = [
        json.loads(next((run_dir / "tasks" / f"tick-{n}").glob("outcome-*.json")).read_text())
        for n in range(1, ROUNDS + 1)
    ]
    assert [t["kind"] for t in ticks] == ["completed"] * ROUNDS
    assert [t["value"]["n"] for t in ticks] == list(range(1, ROUNDS + 1))

    snapshot = bus.snapshot()
    agents = snapshot.agents_by_task[bus.task(task_dir).id]
    assert len(agents) == ROUNDS + 1

    final = json.loads((task_dir / f"outcome-{agents[-1]}.json").read_text())
    assert final["kind"] == "completed"
    assert final["value"] == {"ns": list(range(1, ROUNDS + 1))}

    collected = [
        snapshot.attempts[newest_agent(snapshot, bus.task(run_dir / "tasks" / f"tick-{n}").id)]
        for n in range(1, ROUNDS + 1)
    ]
    assert [isinstance(a, Collected) for a in collected] == [True] * ROUNDS
