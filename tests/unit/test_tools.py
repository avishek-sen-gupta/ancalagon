import json
import pathlib

import ancalagon.config.config
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
from ancalagon.worker import build_registry
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(exist_ok=True)
    outputs = write_root / "outputs"
    outputs.mkdir(exist_ok=True)
    return ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=outputs,
        summary_chars=50,
        agent_id=17,
    )


def test_file_tools_round_trip_and_report_scope_violations_as_values(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    registry = Registry([ReadFile(), WriteFile(), EditFile(), DeleteFile(), ListDir()])

    assert sorted(registry.names()) == [
        "delete_file",
        "edit_file",
        "list_dir",
        "read_file",
        "write_file",
    ]
    assert {s.name for s in registry.schemas()} == set(registry.names())

    target = ctx.workspace.write_root / "note.txt"
    written = registry.get("write_file").run(
        f'{{"path": "{target}", "content": "hello world"}}', ctx
    )
    assert written.ok is True
    assert target.read_text() == "hello world"

    read = registry.get("read_file").run(f'{{"path": "{target}"}}', ctx)
    assert read.ok is True
    assert read.path.read_text() == "hello world"
    assert read.byte_count == 11

    edited = registry.get("edit_file").run(
        f'{{"path": "{target}", "old": "world", "new": "there"}}', ctx
    )
    assert edited.ok is True
    assert target.read_text() == "hello there"

    missing_edit = registry.get("edit_file").run(
        f'{{"path": "{target}", "old": "absent", "new": "x"}}', ctx
    )
    assert missing_edit.ok is False
    assert "not found" in missing_edit.error
    assert target.read_text() == "hello there"

    listed = registry.get("list_dir").run(f'{{"path": "{ctx.workspace.write_root}"}}', ctx)
    assert listed.ok is True
    assert "note.txt" in listed.path.read_text()

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    denied = registry.get("read_file").run(f'{{"path": "{outside}"}}', ctx)
    assert isinstance(denied, ToolResult)
    assert denied.ok is False
    assert "outside" in denied.error

    denied_write = registry.get("write_file").run(f'{{"path": "{outside}", "content": "x"}}', ctx)
    assert denied_write.ok is False
    assert outside.read_text() == "secret"

    deleted = registry.get("delete_file").run(f'{{"path": "{target}"}}', ctx)
    assert deleted.ok is True
    assert not target.exists()

    big = ctx.workspace.write_root / "big.txt"
    big.write_text("\n".join(f"line {i}" for i in range(60)))
    first = registry.get("read_file").run(f'{{"path": "{big}"}}', ctx)
    assert first.ok is True
    assert first.truncated is True
    assert "line 0" in first.summary
    assert "of 60" in first.summary
    shown = int(first.summary.rsplit("offset=", 1)[1].split(" ")[0])
    assert 0 < shown < 60

    rest = registry.get("read_file").run(f'{{"path": "{big}", "offset": {shown}}}', ctx)
    assert f"line {shown}" in rest.summary

    tail = registry.get("read_file").run(f'{{"path": "{big}", "offset": 58}}', ctx)
    assert "line 59" in tail.summary
    assert "end of file" in tail.summary
    assert tail.truncated is False

    relative = registry.get("read_file").run('{"path": "nope.txt"}', ctx)
    assert relative.ok is False
    assert "Relative paths resolve" in relative.error

    absent = registry.get("read_file").run(
        f'{{"path": "{ctx.workspace.write_root / "nope.txt"}"}}', ctx
    )
    assert absent.ok is False
    assert "no file at" in absent.error


def test_search_and_parse_tools_write_outputs_and_never_mutate_inputs(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    source = ctx.workspace.write_root / "sample.py"
    source.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    before = source.read_text()

    found = Ripgrep().run(
        f'{{"pattern": "def (alpha|beta)", "roots": ["{ctx.workspace.write_root}"]}}', ctx
    )
    assert found.ok is True
    assert [l.split(":", 2)[2].strip() for l in found.path.read_text().splitlines()] == [
        "def alpha():",
        "def beta():",
    ]

    structured = Ripgrep().run(
        f'{{"pattern": "def alpha", "roots": ["{ctx.workspace.write_root}"], "structured": true}}',
        ctx,
    )
    matches = [
        r
        for r in (json.loads(line) for line in structured.path.read_text().splitlines())
        if r["type"] == "match"
    ]
    assert str(source) in [m["data"]["path"]["text"] for m in matches]

    missing = Ripgrep().run(
        f'{{"pattern": "zzz_absent", "roots": ["{ctx.workspace.write_root}"]}}', ctx
    )
    assert missing.ok is True
    assert missing.path.read_text() == ""

    streamed = Sed().run(f'{{"script": "s/alpha/gamma/", "path": "{source}"}}', ctx)
    assert streamed.ok is True
    assert "gamma" in streamed.path.read_text()
    assert source.read_text() == before

    parsed = TreeSitter().run(f'{{"path": "{source}", "language": "python"}}', ctx)
    assert parsed.ok is True
    assert '"type": "function_definition"' in parsed.path.read_text()

    unsupported = TreeSitter().run(f'{{"path": "{source}", "language": "cobol"}}', ctx)
    assert unsupported.ok is False
    assert "unsupported language" in unsupported.error

    denied = Sed().run(f'{{"script": "s/a/b/", "path": "{tmp_path / "outside.txt"}"}}', ctx)
    assert denied.ok is False


def test_registry_withholds_delegate_once_depth_reaches_max_depth(tmp_path: pathlib.Path):
    config = ancalagon.config.config.Config(
        write_root=tmp_path,
        read_roots=(tmp_path,),
        model="claude-opus-5",
        max_tokens=100,
        num_retries=0,
        request_timeout_s=10,
        budget=Budget(turns=1, tool_calls=1),
        max_concurrent_agents=1,
        agent_timeout_s=1,
        max_depth=1,
        tools=[],
        summary_chars=100,
    )
    submit = SubmitAnswer(FreeText)
    need_input = NeedInput()
    at_root = build_registry(
        config, tmp_path, parent=0, depth=0, submit=submit, need_input=need_input
    )
    at_limit = build_registry(
        config, tmp_path, parent=1, depth=1, submit=submit, need_input=need_input
    )

    assert "delegate" in at_root.names()
    assert "need_input" in at_root.names()
    assert "delegate" not in at_limit.names()
    assert "need_input" in at_limit.names()
    assert "submit_answer" in at_root.names()
    submit = at_root.get("submit_answer")
    assert json.loads(submit.schema().parameters_json)["properties"].keys() == {"text"}
