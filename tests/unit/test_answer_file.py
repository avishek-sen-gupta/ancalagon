import json
import pathlib

from ancalagon.bus.no_bus import NO_BUS
from ancalagon.clock.system_clock import SystemClock
from ancalagon.config.config import Config
from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.answer_status import AnswerStatus
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.role import Role
from ancalagon.contracts.schema_guided import SchemaGuided
from ancalagon.contracts.submitted import Submitted
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.session_for import build_registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.adheres_to_schema import adheres_to_schema
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import submitting
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.workspace.workspace import Workspace
from tests.unit.conftest import finite_budget

ANSWER_FILE = ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile")


class Guided(SchemaGuided, frozen=True):
    pass


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
        clock=SystemClock(),
        fs=RealFileSystem(),
        web=FakeWebClient({}),
        bus=NO_BUS,
    )
    assert sorted(registry.names()) == ["idle", "read_file", "submit_answer_as_file"]


def test_submitting_a_file_ends_the_run_and_refuses_a_file_that_is_not_there(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    answer = tmp_path / "ws" / "record.json"
    answer.write_text('{"values": []}')
    tool = SubmitAnswerAsFile()

    accepted = tool.run(
        AnswerFile(
            status=AnswerStatus.COMPLETE,
            summary="one record with no values",
            path=pathlib.PurePath(answer),
        ),
        ctx,
    )
    assert accepted.ok
    assert isinstance(accepted.summary, Submitted)
    assert accepted.summary.answer == AnswerFile(
        status=AnswerStatus.COMPLETE,
        summary="one record with no values",
        path=pathlib.PurePath(answer),
    )

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


def test_the_schema_hook_accepts_a_conforming_file_names_every_fault_and_refuses_what_it_cannot_read(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    schema = write_root / "record.schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name", "values"],
                "properties": {
                    "name": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "integer"}},
                },
            }
        )
    )
    answer = write_root / "record.json"
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
        input=Guided(output_schema=pathlib.PurePath(schema)),
    )
    submitted = AnswerFile(
        status=AnswerStatus.COMPLETE, summary="a record", path=pathlib.PurePath(answer)
    )

    answer.write_text(json.dumps({"name": "a", "values": [1, 2]}))
    assert adheres_to_schema(submitted, ctx) == Accepted(value=submitted)

    answer.write_text(json.dumps({"values": [1, "two"]}))
    refusal = adheres_to_schema(submitted, ctx)
    assert isinstance(refusal, Refused)
    assert "/values/1" in refusal.reason
    assert "'name' is a required property" in refusal.reason

    answer.unlink()
    assert adheres_to_schema(submitted, ctx) == Refused(
        reason=f"the answer file you submitted, {answer}, does not exist"
    )

    answer.write_text("{oops")
    unparsable = adheres_to_schema(submitted, ctx)
    assert isinstance(unparsable, Refused)
    assert unparsable.reason.startswith(
        f"the answer file you submitted, {answer}, is not valid JSON: "
    )

    answer.write_text(json.dumps({"name": "a", "values": [1, 2]}))
    schema.write_text("{oops")
    unparsable_schema = adheres_to_schema(submitted, ctx)
    assert isinstance(unparsable_schema, Refused)
    assert unparsable_schema.reason.startswith(
        f"the schema this task named, {schema}, is not valid JSON: "
    )

    schema.unlink()
    assert adheres_to_schema(submitted, ctx) == Refused(
        reason=f"the schema this task named, {schema}, does not exist"
    )

    unguided = ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )
    assert adheres_to_schema(submitted, unguided) == Refused(
        reason="this role's input contract does not name an output schema: FreeText"
    )
