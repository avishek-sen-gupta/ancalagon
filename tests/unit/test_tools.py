import pathlib

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
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

    long_content = "x" * 500
    big = ctx.workspace.write_root / "big.txt"
    big.write_text(long_content)
    result = registry.get("read_file").run(f'{{"path": "{big}"}}', ctx)
    assert result.truncated is True
    assert len(result.summary) <= 50
    assert result.path.read_text() == long_content


def test_search_and_parse_tools_write_outputs_and_never_mutate_inputs(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    source = ctx.workspace.write_root / "sample.py"
    source.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    before = source.read_text()

    found = Ripgrep().run(
        f'{{"pattern": "def (alpha|beta)", "roots": ["{ctx.workspace.write_root}"]}}', ctx
    )
    assert found.ok is True
    assert "alpha" in found.path.read_text()
    assert "beta" in found.path.read_text()

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
