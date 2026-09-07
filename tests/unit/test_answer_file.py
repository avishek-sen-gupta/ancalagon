import pathlib

from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.answer_status import AnswerStatus
from ancalagon.contracts.submitted import Submitted
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.tools.submit.submitting import submitting
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=1,
    )


def test_the_role_chooses_which_terminal_tool_it_submits_with():
    assert submitting(("read_file", "submit_answer")) == SubmitAnswer.name
    assert submitting(("read_file", "submit_answer_as_file")) == SubmitAnswerAsFile.name
    assert submitting(("submit_answer", "submit_answer_as_file")) == SubmitAnswerAsFile.name


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
    assert "absent.json" in missing.error
