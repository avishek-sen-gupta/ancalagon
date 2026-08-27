import json
import pathlib
import threading
import time

from ancalagon.attempt.closed import Closed
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.function_ref import FunctionRef
from ancalagon.contracts.role import Role
from ancalagon.env.real_environment import RealEnvironment
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.sandbox.unsandboxed import Unsandboxed
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.supervisor.spawn_by_run import SpawnByRun
from ancalagon.supervisor.subprocess_spawner import SubprocessSpawner
from ancalagon.supervisor.supervisor import Supervisor
from ancalagon.contracts.watch_request import WatchRequest
from tests.integration.prepared_run import prepared_run_dir

WATCHING = ClassRef(module=WatchRequest.__module__, name="WatchRequest")


def test_a_watcher_process_wakes_the_supervisor_the_way_any_child_does(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    run_dir = prepared_run_dir(tmp_path / "ws" / "runs" / "board")
    board = tmp_path / "blackboard.md"
    board.write_text("opening claim\n")

    task_dir = run_dir / "tasks" / "watcher"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    spec = AgentSpec[WatchRequest](
        task_id="watcher",
        role=Role(
            behaviour="Wait for the blackboard.",
            run=FunctionRef(module="ancalagon.watch.watch_for", name="watch_for"),
            input=WATCHING,
            tools=(),
            budget=Budget(turns=0, tool_calls=0),
        ),
        goal="Wake me when the blackboard changes.",
        input=WatchRequest(path=str(board), since=fs.changed_at(board), poll_s=0.05),
    )
    fs.write_text(task_dir / "spec.json", spec.model_dump_json())

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs)
    agent = bus.enqueue(task_dir, parent_agent=HUMAN)

    (tmp_path / "watcher.toml").write_text("")
    ordinary = SubprocessSpawner(
        run_dir=run_dir,
        config_path=tmp_path / "watcher.toml",
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.worker",
        sandbox=Unsandboxed(),
    )
    watching = SubprocessSpawner(
        run_dir=run_dir,
        config_path=tmp_path / "watcher.toml",
        environment=RealEnvironment(),
        fs=fs,
        module="ancalagon.deterministic.run",
        sandbox=Unsandboxed(),
    )
    supervisor = Supervisor(
        bus=LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs),
        spawner=SpawnByRun(default=ordinary, deterministic=watching, fs=fs),
        max_concurrent=2,
        timeout_s=30,
        clock=SystemClock(),
        fs=fs,
    )

    def append_later() -> None:
        time.sleep(1.0)
        board.write_text("opening claim\na second claim\n")

    threading.Thread(target=append_later, daemon=True).start()
    try:
        supervisor.run_until_idle()
    finally:
        supervisor.shutdown()

    written = json.loads((task_dir / f"outcome-{agent}.json").read_text())
    assert written["kind"] == "completed"
    assert written["value"]["path"] == str(board)

    snapshot = bus.snapshot()
    attempt = snapshot.attempts[newest_agent(snapshot, bus.task(task_dir).id)]
    assert isinstance(attempt, Closed)
    assert attempt.verdict is AgentStatus.COMPLETED
