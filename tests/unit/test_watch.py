import json
import pathlib
import time

import pytest

from ancalagon.clock.clock import Clock
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.config.config import Config
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawn_by_input import SpawnByInput
from ancalagon.supervisor.spawner import Spawner
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.files.read_args import ReadArgs
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.watch.watch_args import WatchArgs
from ancalagon.tools.watch.watch_file import WatchFile
from ancalagon.watch.watch import main, watch_for
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.worker import build_registry
from ancalagon.workspace.workspace import Workspace


class FakeProcess(Process):
    pid = 0

    def poll(self) -> int | None:
        return 0

    def kill(self) -> None:
        return None


def _config(tmp_path: pathlib.Path, roles: dict[str, Role]) -> Config:
    return Config(
        write_root=tmp_path,
        read_roots=(tmp_path,),
        model="m",
        roles=roles,
        max_depth=1,
    )


ROLE = Role(behaviour="Wait.", tools=(), budget=Budget(turns=0, tool_calls=0))


class WritingClock(Clock):
    def __init__(self, board: pathlib.Path, after: int):
        self.inner = FakeClock()
        self.board = board
        self.after = after
        self.slept = 0

    def now(self):
        return self.inner.now()

    def time(self) -> float:
        return self.inner.time()

    def sleep(self, seconds: float) -> None:
        self.slept += 1
        self.inner.sleep(seconds)
        if self.slept == self.after:
            self.board.write_text("a claim appeared\n")


def test_a_watcher_waits_until_the_file_it_was_given_changes(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    board = tmp_path / "blackboard.md"
    board.write_text("first\n")
    before = fs.changed_at(board)
    clock = WritingClock(board, after=3)

    watched = watch_for(WatchRequest(path=str(board), since=before), fs, clock)

    assert clock.slept == 3
    assert watched.path == str(board)
    assert watched.at > before


def test_a_watcher_leaves_the_outcome_a_supervisor_reads_and_nothing_else(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    task_dir = tmp_path / "tasks" / "watcher"
    task_dir.mkdir(parents=True)
    board = tmp_path / "blackboard.md"
    board.write_text("already written\n")

    spec = AgentSpec[WatchRequest](
        task_id="watcher",
        role=ROLE,
        goal="Wake me when the blackboard changes.",
        input=WatchRequest(path=str(board), since=0.0),
    )
    fs.write_text(task_dir / "spec.json", spec.model_dump_json())

    assert main(task_dir, 4) == 0

    written = json.loads((task_dir / "outcome-4.json").read_text())
    assert written["kind"] == "completed"
    assert written["value"]["path"] == str(board)
    assert written["spent"] == {"turns": 0, "tool_calls": 0}
    assert sorted(p.name for p in task_dir.iterdir()) == ["outcome-4.json", "spec.json"]


def test_a_watcher_records_a_failure_the_way_a_worker_does(tmp_path: pathlib.Path):
    task_dir = tmp_path / "tasks" / "broken"
    task_dir.mkdir(parents=True)

    assert main(task_dir, 9) == 1

    written = json.loads((task_dir / "outcome-9.json").read_text())
    assert written["kind"] == "failed"
    assert "spec.json" in written["error"]


def test_a_dispatching_spawner_picks_the_watcher_by_the_contract_the_role_declares(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    asked: list[tuple[str, pathlib.PurePath]] = []

    class Noting(Spawner):
        def __init__(self, label: str):
            self.label = label

        def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
            asked.append((self.label, task_dir))
            return FakeProcess()

    def task(name: str, ref: ClassRef) -> pathlib.PurePath:
        made = tmp_path / name
        made.mkdir(parents=True, exist_ok=True)
        spec = AgentSpec[FreeText](
            task_id=name,
            role=ROLE.model_copy(update={"input": ref}),
            goal="g",
            input=FreeText(text="t"),
        )
        fs.write_text(made / "spec.json", spec.model_dump_json())
        return made

    watching = ClassRef(module=WatchRequest.__module__, name="WatchRequest")
    ordinary = ClassRef(module=FreeText.__module__, name="FreeText")
    dispatch = SpawnByInput(
        default=Noting("worker"), by_input={"WatchRequest": Noting("watcher")}, fs=fs
    )

    dispatch.spawn(task("a", watching), 1)
    dispatch.spawn(task("b", ordinary), 2)

    assert [label for label, _ in asked] == ["watcher", "worker"]


def test_a_watch_resumes_from_the_read_the_agent_logged_not_from_the_file_now(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    run_dir = tmp_path / "ws" / "runs" / "r2"
    fs.mkdir(run_dir, parents=True, exist_ok=True)
    migrate_file(run_dir / "bus.db", latest_version(fs), fs)
    board = run_dir / "blackboard.md"
    fs.write_text(board, "a claim\n")

    ctx = ToolContext(
        workspace=Workspace(fs, write_root=run_dir, read_roots=(run_dir,)),
        task_dir=run_dir,
        summary_chars=200,
        agent_id=1,
    )
    tool = WatchFile(role=ROLE, run_dir=run_dir, parent=1, clock=SystemClock(), fs=fs)

    # Never read, so nothing has been seen and the first watch returns everything.
    assert tool.run(WatchArgs(task_id="w0", path=board), ctx).ok is True
    assert (
        json.loads((run_dir / "tasks" / "w0-r2" / "spec.json").read_text())["input"]["since"] == 0.0
    )

    assert ReadFile(FakeClock()).run(ReadArgs(path=board), ctx).ok is True
    read_at = fs.changed_at(board)

    # A later read of some other file must not be mistaken for a read of the board.
    time.sleep(0.01)
    elsewhere = run_dir / "notes.md"
    fs.write_text(elsewhere, "unrelated\n")
    assert ReadFile(FakeClock()).run(ReadArgs(path=elsewhere), ctx).ok is True
    assert fs.changed_at(elsewhere) > read_at

    # Others append while this agent works, and then stop.
    time.sleep(0.01)
    fs.write_text(board, "a claim\nanother claim\n")
    assert fs.changed_at(board) > read_at

    # The baseline is the read, not the file as it is now, or those writes are never woken on.
    assert tool.run(WatchArgs(task_id="w1", path=board), ctx).ok is True
    assert json.loads((run_dir / "tasks" / "w1-r2" / "spec.json").read_text())["input"][
        "since"
    ] == (read_at)

    outside = tool.run(WatchArgs(task_id="w2", path=tmp_path / "elsewhere.md"), ctx)
    assert outside.ok is False
    assert "outside read_roots" in outside.error


def test_watch_file_is_offered_only_where_a_role_declares_the_watch_contract(
    tmp_path: pathlib.Path,
):
    fs = RealFileSystem()
    migrate_file(tmp_path / "bus.db", latest_version(fs), fs)
    watcher = Role(
        behaviour="Wait.",
        input=ClassRef(module=WatchRequest.__module__, name="WatchRequest"),
        tools=(),
        budget=Budget(turns=0, tool_calls=0),
    )
    participant = Role(
        behaviour="Collaborate.",
        tools=("read_file", "watch_file"),
        budget=Budget(turns=4, tool_calls=8),
    )

    def names(roles: dict[str, Role]) -> list[str]:
        return sorted(
            build_registry(
                _config(tmp_path, roles),
                TaskSpec(task_id="t", role=participant, goal="g"),
                tmp_path,
                parent=1,
                depth=0,
                output_class=FreeText,
                clock=SystemClock(),
                fs=fs,
            ).names()
        )

    assert names({"watcher": watcher, "participant": participant}) == [
        "idle",
        "read_file",
        "submit_answer",
        "watch_file",
    ]

    with pytest.raises(ValueError, match="watch_file"):
        names({"participant": participant})


def test_two_agents_watching_the_same_file_get_a_watcher_each(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    run_dir = tmp_path / "ws" / "runs" / "r3"
    fs.mkdir(run_dir, parents=True, exist_ok=True)
    migrate_file(run_dir / "bus.db", latest_version(fs), fs)
    board = run_dir / "blackboard.md"
    fs.write_text(board, "shared\n")
    workspace = Workspace(fs, write_root=run_dir, read_roots=(run_dir,))

    def watching(task: str, agent: int) -> ToolContext:
        return ToolContext(
            workspace=workspace,
            task_dir=run_dir / "tasks" / task,
            summary_chars=200,
            agent_id=agent,
        )

    # Both analysts pick the same name for their waiting task, as three of them did.
    for task, agent in (("registry_analyst", 2), ("session_analyst", 3)):
        tool = WatchFile(role=ROLE, run_dir=run_dir, parent=agent, clock=SystemClock(), fs=fs)
        assert tool.run(WatchArgs(task_id="wait", path=board), watching(task, agent)).ok is True

    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), fs)
    watchers = {
        pathlib.PurePath(t.dir).name: t.parent_agent
        for t in bus.snapshot().tasks
        if "wait" in pathlib.PurePath(t.dir).name
    }
    assert watchers == {"wait-registry_analyst": 2, "wait-session_analyst": 3}
