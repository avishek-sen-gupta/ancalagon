import json
import pathlib

import pydantic
import pytest

from ancalagon.tools.artifacts.edit_json import EditJson
from ancalagon.tools.artifacts.json_edit_args import JsonEditArgs
from ancalagon.tools.artifacts.json_op import JsonOp
from ancalagon.tools.artifacts.json_path import JsonPath, path_of
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.fs.real_file_system import RealFileSystem
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


def test_a_json_pointer_becomes_the_path_jq_indexes_with():
    assert path_of("/values/0/name") == JsonPath(root=("values", 0, "name"))
    assert path_of("") == JsonPath(root=())
    assert path_of("/a~1b/c~0d") == JsonPath(root=("a/b", "c~d"))
    assert path_of("/~01") == JsonPath(root=("~1",))
    assert path_of("/values/0/name").model_dump_json() == '["values",0,"name"]'

    with pytest.raises(pydantic.ValidationError):
        JsonEditArgs(path=pathlib.PurePath("x.json"), op=JsonOp.SET, pointer="values/0")


def test_edit_json_sets_appends_and_removes_in_place(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    target = tmp_path / "ws" / "answer.json"
    target.write_text('{"values": [{"name": "a"}], "complete": false}')
    tool = EditJson()

    setting = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath(target),
            op=JsonOp.SET,
            pointer="/values/0/name",
            value='"renamed"',
        ),
        ctx,
    )
    assert setting.ok
    appending = tool.run(
        JsonEditArgs(
            path=pathlib.PurePath(target),
            op=JsonOp.APPEND,
            pointer="/values",
            value='{"name": "b"}',
        ),
        ctx,
    )
    assert appending.ok
    removing = tool.run(
        JsonEditArgs(path=pathlib.PurePath(target), op=JsonOp.REMOVE, pointer="/complete"),
        ctx,
    )
    assert removing.ok

    assert json.loads(target.read_text()) == {"values": [{"name": "renamed"}, {"name": "b"}]}


def test_edit_json_refuses_a_path_outside_the_write_root_and_a_value_jq_rejects(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    target = tmp_path / "ws" / "answer.json"
    target.write_text("{}")
    tool = EditJson()

    outside = tool.run(
        JsonEditArgs(path=pathlib.PurePath("/etc/passwd"), op=JsonOp.SET, pointer="/x", value="1"),
        ctx,
    )
    assert not outside.ok
    assert "/etc/passwd" in outside.error

    bad = tool.run(
        JsonEditArgs(path=pathlib.PurePath(target), op=JsonOp.SET, pointer="/x", value="not json"),
        ctx,
    )
    assert not bad.ok
    assert "argjson" in bad.error
    assert target.read_text() == "{}"
