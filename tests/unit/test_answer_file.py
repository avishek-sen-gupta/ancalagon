import json
import pathlib

import pydantic

from ancalagon.bus.no_bus import NO_BUS
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.answer_status import AnswerStatus
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.role import Role
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.session_for import build_registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import submitting
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.workspace.workspace import Workspace
from tests.unit.conftest import finite_budget

ANSWER_FILE = ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile")


class Record(pydantic.BaseModel, frozen=True):
    name: str
    values: tuple[int, ...]


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )


def test_the_role_chooses_which_terminal_tool_it_submits_with(tmp_path: pathlib.Path):
    assert submitting(("read_file", "submit_answer")) == SubmitAnswer.name
    assert submitting(("read_file", "submit_answer_as_file")) == SubmitAnswerAsFile.name
    assert submitting(("submit_answer", "submit_answer_as_file")) == SubmitAnswerAsFile.name

    role = Role(
        behaviour="You answer.",
        answer=ANSWER_FILE,
        answer_file=ClassRef(module=__name__, name="Record"),
        tools=("read_file", "submit_answer", "submit_answer_as_file"),
        budget=finite_budget(1, 1),
    )
    registry = build_registry(
        Config(write_root=tmp_path, read_roots=(tmp_path,), model="m", roles={"root": role}),
        TaskSpec(task_id="root", role=role, goal="g"),
        tmp_path,
        parent=1,
        depth=0,
        output_class=AnswerFile,
        answer_file_class=Record,
        clock=SystemClock(),
        fs=RealFileSystem(),
        web=FakeWebClient({}),
        bus=NO_BUS,
    )
    assert sorted(registry.names()) == ["idle", "read_file", "submit_answer_as_file"]


def test_submitting_a_file_validates_it_into_the_role_s_class_and_refuses_what_does_not_fit(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    answer = tmp_path / "ws" / "record.json"
    tool = SubmitAnswerAsFile(Record)
    submitted = AnswerFile(
        status=AnswerStatus.COMPLETE, summary="a record", path=pathlib.PurePath(answer)
    )

    assert json.dumps(Record.model_json_schema()) in tool.description

    answer.write_text(json.dumps({"name": "a", "values": [1, 2]}))
    accepted = tool.run(submitted, ctx)
    assert accepted.ok
    assert isinstance(accepted.summary, Submitted)
    assert accepted.summary.answer == submitted

    answer.write_text(json.dumps({"values": [1, "two"]}))
    mismatched = tool.run(submitted, ctx)
    assert not mismatched.ok
    assert mismatched.error == (
        f"{answer} does not match Record:\n"
        "/name: Field required\n"
        "/values/1: Input should be a valid integer, unable to parse string as an integer"
    )

    answer.write_text("{oops")
    unparsable = tool.run(submitted, ctx)
    assert not unparsable.ok
    assert unparsable.error.startswith(f"{answer} does not match Record:\n/: Invalid JSON: ")

    missing = tool.run(
        AnswerFile(
            status=AnswerStatus.PARTIAL,
            summary="nothing written yet",
            path=pathlib.PurePath(tmp_path / "ws" / "absent.json"),
        ),
        ctx,
    )
    assert not missing.ok
    assert missing.error == f"no answer file at {tmp_path / 'ws' / 'absent.json'}"
