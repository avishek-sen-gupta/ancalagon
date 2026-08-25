import json
import pathlib

from ancalagon.clock.clock import Clock
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.role import Role
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawn_by_input import SpawnByInput
from ancalagon.supervisor.spawner import Spawner
from ancalagon.watch.watch import main, watch_for
from ancalagon.watch.watch_request import WatchRequest


class FakeProcess(Process):
    pid = 0

    def poll(self) -> int | None:
        return 0

    def kill(self) -> None:
        return None


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
    before = fs.mtime(board)
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
