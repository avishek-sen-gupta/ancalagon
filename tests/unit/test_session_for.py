import json
import pathlib

from ancalagon.children.no_children import NO_CHILDREN
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.config.config import Config
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.letterbox.no_letterbox import NO_LETTERBOX
from ancalagon.llm.fake_llm import FakeLLM
from ancalagon.llm.unmetered import UNMETERED
from ancalagon.session_for import session_for
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript
from ancalagon.watch.watch_for import WATCH_FOR
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace
from tests.unit.conftest import finite_budget

SOLO = Role(
    behaviour="Work alone.",
    tools=("delegate_solo", "watch_file", "idle", "submit_answer"),
    budget=finite_budget(4, 8),
)

WATCHER = Role(behaviour="Watch.", run=WATCH_FOR, tools=(), budget=finite_budget(0, 0))


def test_a_session_with_no_bus_gets_tools_that_cannot_queue(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    write_root = tmp_path / "ws"
    task_dir = write_root / "tasks" / "solo"
    fs.mkdir(pathlib.PurePath(task_dir), parents=True, exist_ok=True)
    config = Config(
        write_root=pathlib.PurePath(write_root),
        read_roots=(pathlib.PurePath(write_root),),
        model="some-provider/no-model-is-called",
        roles={"solo": SOLO, "watcher": WATCHER},
    )
    spec = TaskSpec(task_id="solo", role=SOLO, goal="Answer it.")
    ctx = ToolContext(
        workspace=Workspace.from_config(config, fs),
        task_dir=pathlib.PurePath(task_dir),
        summary_chars=config.summary_chars,
        agent_id=1,
        input=FreeText(text="Answer it."),
    )
    transcript = Transcript(fs, path=pathlib.PurePath(task_dir / "transcript.jsonl"), agent_id=1)

    session = session_for(
        config,
        spec,
        ctx,
        transcript,
        pathlib.PurePath(tmp_path / "runs" / "solo"),
        FakeLLM([]),
        FakeClock(),
        fs,
        RealWebClient(),
    )
    transcript.close()

    bound = session.registry.get("delegate_solo")
    refused = bound.invoke(json.dumps({"task_id": "t1", "goal": "g", "input": {"text": "go"}}), ctx)
    assert refused.ok is False
    assert refused.error == "cannot queue task t1: this session has no bus"
    assert session.children is NO_CHILDREN
    assert session.letterbox is NO_LETTERBOX
    assert session.meter is UNMETERED
