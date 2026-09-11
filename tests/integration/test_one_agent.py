import pathlib

from ancalagon.clock.fake_clock import FakeClock
from ancalagon.config.config import Config
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.llm.fake_llm import FakeLLM
from ancalagon.session_for import session_for
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript
from ancalagon.web.real_web_client import RealWebClient
from ancalagon.workspace.workspace import Workspace
from tests.unit.conftest import finite_budget

DELEGATED = Reply(
    blocks=[
        ToolUse(
            id="tu_0",
            name="delegate_solo",
            arguments='{"task_id": "t1", "goal": "g", "input": {"text": "go"}}',
        )
    ],
    stop_reason="tool_calls",
)

ANSWERED = Reply(
    blocks=[ToolUse(id="tu_1", name="submit_answer", arguments='{"text": "Paris"}')],
    stop_reason="tool_calls",
)


def test_a_host_runs_one_agent_with_no_bus_and_no_subprocess(tmp_path: pathlib.Path):
    fs = RealFileSystem()
    write_root = tmp_path / "ws"
    task_dir = write_root / "tasks" / "solo"
    fs.mkdir(pathlib.PurePath(task_dir), parents=True, exist_ok=True)
    role = Role(
        behaviour="Answer the question you are given.",
        tools=("delegate_solo", "submit_answer"),
        budget=finite_budget(2, 2),
    )
    config = Config(
        write_root=pathlib.PurePath(write_root),
        read_roots=(pathlib.PurePath(write_root),),
        model="some-provider/no-model-is-called",
        roles={"solo": role},
    )
    spec = TaskSpec(task_id="solo", role=role, goal="What is the capital of France?")
    given = FreeText(text="What is the capital of France?")
    ctx = ToolContext(
        workspace=Workspace.from_config(config, fs),
        task_dir=pathlib.PurePath(task_dir),
        summary_chars=config.summary_chars,
        agent_id=1,
        input=given,
    )
    transcript = Transcript(fs, path=pathlib.PurePath(task_dir / "transcript.jsonl"), agent_id=1)

    llm = FakeLLM([DELEGATED, ANSWERED])
    try:
        session = session_for(
            config,
            spec,
            ctx,
            transcript,
            pathlib.PurePath(tmp_path / "runs" / "solo"),
            llm,
            FakeClock(),
            fs,
            RealWebClient(),
        )
        produced = session.run()
    finally:
        transcript.close()

    refusals = [b for m in llm.seen[1] for b in m.blocks if isinstance(b, ToolResultBlock)]
    assert len(refusals) == 1
    assert refusals[0].is_error is True
    assert refusals[0].content.startswith("cannot queue task t1: this session has no bus")

    assert isinstance(produced, Completed)
    assert produced.value.model_dump() == {"text": "Paris"}
    assert list(tmp_path.rglob("bus.db")) == []
