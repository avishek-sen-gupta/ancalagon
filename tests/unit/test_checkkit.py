import pathlib

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.refused import Refused
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.workspace import Workspace
from checkkit.checks import cited_files_exist


def test_a_cited_file_must_exist_under_a_read_root_and_not_only_under_a_write_root(
    tmp_path: pathlib.Path,
):
    source = tmp_path / "src"
    (source / "bus").mkdir(parents=True)
    (source / "bus" / "lifecycle.py").write_text("")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "scratch.py").write_text("")
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(notes,), read_roots=(tmp_path,)),
        task_dir=notes / "task",
        summary_chars=200,
        agent_id=1,
    )

    by_name = FreeText(text="The bus lives in lifecycle.py.")
    assert cited_files_exist(by_name, ctx) == Accepted(value=by_name)

    by_path = FreeText(text=f"See {source / 'bus' / 'lifecycle.py'}.")
    assert cited_files_exist(by_path, ctx) == Accepted(value=by_path)

    written_by_the_agent = FreeText(text="The answer is in scratch.py and absent.py.")
    assert cited_files_exist(written_by_the_agent, ctx) == Refused(
        reason=(
            "these cited paths do not exist: ['absent.py', 'scratch.py']. "
            "Cite only files you opened, and copy the path exactly as the tool "
            "reported it."
        )
    )
