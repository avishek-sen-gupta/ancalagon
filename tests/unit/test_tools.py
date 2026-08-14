import json
import pathlib

import pydantic
import pytest

import ancalagon.config.config
from ancalagon.bus.bus import Bus
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.bus.agent_status import AgentStatus
from ancalagon.bus.event_source import EventSource
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate import Delegate
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.artifacts.convert_document import ConvertDocument
from ancalagon.tools.artifacts.extract_strings import ExtractStrings
from ancalagon.tools.artifacts.file_type import FileType
from ancalagon.tools.artifacts.query_json import QueryJson
from ancalagon.tools.history.git_history import GitHistory
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
from ancalagon.tools.survey.code_stats import CodeStats
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
    assert "no file or directory at" in absent.error


def test_search_and_parse_tools_write_outputs_and_never_let_arguments_become_options(
    tmp_path: pathlib.Path,
):
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

    flags = ctx.workspace.write_root / "flags.txt"
    flags.write_text("a line mentioning --files here\n")

    literal = Ripgrep().run(
        json.dumps({"pattern": "--files", "roots": [str(ctx.workspace.write_root)]}), ctx
    )
    assert literal.ok is True
    assert [l.split(":", 2)[2] for l in literal.path.read_text().splitlines()] == [
        "a line mentioning --files here"
    ]

    dashed = Sed().run(json.dumps({"script": "s/--files/--flags/", "path": str(flags)}), ctx)
    assert dashed.ok is True
    assert dashed.path.read_text() == "a line mentioning --flags here\n"


def test_registry_withholds_delegate_at_max_depth_and_refuses_unknown_tool_names(
    tmp_path: pathlib.Path,
):
    config = ancalagon.config.config.Config(
        write_root=tmp_path,
        read_roots=(tmp_path,),
        root_behaviour="You investigate.",
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
        compact_above_tokens=0,
        keep_recent_messages=8,
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
    answer_shape = json.loads(at_root.get("submit_answer").schema().parameters_json)
    assert set(answer_shape["properties"]) == {"text"}

    chosen = config.model_copy(update={"tools": ["read_file", "ripgrep"]})
    assert build_registry(
        chosen, tmp_path, parent=0, depth=0, submit=submit, need_input=need_input
    ).names() == ["read_file", "ripgrep"]

    typo = config.model_copy(update={"tools": ["read_file", "rigrep", "grep"]})
    with pytest.raises(ValueError) as refused:
        build_registry(typo, tmp_path, parent=0, depth=0, submit=submit, need_input=need_input)
    assert "'grep', 'rigrep'" in str(refused.value)
    assert "ripgrep" in str(refused.value)


def test_delegate_refuses_a_live_task_and_retries_a_finished_one(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    delegate = Delegate(run_dir=run_dir, parent=1)
    args = json.dumps(
        {
            "task_id": "analyse",
            "behaviour": "b",
            "goal": "g",
            "input_json": "{}",
            "output": "contracts.py:FreeText",
            "turns": 3,
            "tool_calls": 5,
        }
    )
    migrate_file(run_dir / "bus.db", latest_version())
    bus = Bus.open(run_dir / "bus.db")

    assert delegate.run(args, ctx).ok is True
    queued = delegate.run(args, ctx)
    assert queued.ok is False
    assert "already queued" in queued.error

    bus.claim(limit=1)
    claimed = delegate.run(args, ctx)
    assert claimed.ok is False
    assert "already claimed" in claimed.error

    bus.record(1, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=99)
    running = delegate.run(args, ctx)
    assert running.ok is False
    assert "already running" in running.error

    bus.record(1, AgentStatus.CRASHED, EventSource.SUPERVISOR, exit_code=1, summary="died")
    retried = delegate.run(args, ctx)
    assert retried.ok is True

    task_dir = run_dir / "tasks" / "analyse"
    assert [s.agent for s in bus.active_for(task_dir)] == [2]
    assert bus.state(1).status is AgentStatus.CRASHED
    assert bus.state(2).dir == str(task_dir)

    shape = json.loads(delegate.schema().parameters_json)["properties"]["output"]
    assert shape["default"] == "contracts.py:FreeText"
    assert "pattern" in shape

    for bad in ("text", "FreeText", "contracts:FreeText", "contracts.py:"):
        with pytest.raises(pydantic.ValidationError):
            delegate.run(json.dumps({**json.loads(args), "task_id": "o", "output": bad}), ctx)

    omitted = {k: v for k, v in json.loads(args).items() if k != "output"}
    assert delegate.run(json.dumps({**omitted, "task_id": "defaulted"}), ctx).ok is True


def test_survey_and_symbol_tools_report_structure_not_mentions(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root
    (root / "widget.py").write_text(
        "class Widget:\n    def spin(self):\n        return 1\n\n\ndef make_widget():\n"
        "    return Widget()\n"
    )
    (root / "user.py").write_text("from widget import Widget\n\nw = Widget()\nw.spin()\n")

    stats = CodeStats().run(f'{{"roots": ["{root}"]}}', ctx)
    assert stats.ok is True
    assert "Python" in stats.path.read_text()

    defined = FindSymbol().run(f'{{"roots": ["{root}"], "name": "Widget"}}', ctx)
    assert defined.ok is True
    lines = [l for l in defined.path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert "class" in lines[0]
    assert "widget.py" in lines[0]
    assert "user.py" not in defined.path.read_text()

    everything = FindSymbol().run(f'{{"roots": ["{root}"]}}', ctx)
    assert {l.split()[0] for l in everything.path.read_text().splitlines() if l.strip()} >= {
        "Widget",
        "spin",
        "make_widget",
    }

    denied = CodeStats().run(f'{{"roots": ["{tmp_path / "elsewhere"}"]}}', ctx)
    assert denied.ok is False


def test_artifact_and_history_tools_read_what_read_file_cannot(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root

    binary = root / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02CONNECTION_STRING_HERE\x00\xff" * 3)
    kind = FileType().run(f'{{"path": "{binary}"}}', ctx)
    assert kind.ok is True
    assert kind.summary.strip() != ""

    found = ExtractStrings().run(f'{{"path": "{binary}", "min_length": 8}}', ctx)
    assert found.ok is True
    assert "CONNECTION_STRING_HERE" in found.path.read_text()

    doc = root / "graph.json"
    doc.write_text('{"nodes": [{"id": "a"}, {"id": "b"}]}')
    ids = QueryJson().run(f'{{"path": "{doc}", "filter": ".nodes[].id"}}', ctx)
    assert ids.ok is True
    assert ids.path.read_text().split() == ["a", "b"]

    unsafe = QueryJson().run(f'{{"path": "{doc}", "filter": "--version"}}', ctx)
    assert unsafe.ok is False
    assert "may not begin with" in unsafe.error

    page = root / "note.md"
    page.write_text("# Title\n\nSome *emphasis*.\n")
    converted = ConvertDocument().run(f'{{"path": "{page}", "to": "plain"}}', ctx)
    assert converted.ok is True
    assert "Title" in converted.path.read_text()


def test_git_history_reports_intent_and_refuses_option_injection(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    repo = ctx.workspace.write_root
    tracked = repo / "thing.py"
    tracked.write_text("x = 1\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "thing.py"],
        ["git", "commit", "-q", "-m", "workaround for a vendor bug"],
    ):
        run_command(["git", "-C", str(repo), *command[1:]])

    log = GitHistory().run(f'{{"path": "{tracked}", "operation": "log"}}', ctx)
    assert log.ok is True
    assert "workaround for a vendor bug" in log.path.read_text()

    blame = GitHistory().run(f'{{"path": "{tracked}", "operation": "blame"}}', ctx)
    assert blame.ok is True
    assert "x = 1" in blame.path.read_text()

    with pytest.raises(pydantic.ValidationError):
        GitHistory().run(
            f'{{"path": "{tracked}", "operation": "show", "rev": "--upload-pack=x"}}', ctx
        )

    missing = GitHistory().run(f'{{"path": "{tracked}", "operation": "show"}}', ctx)
    assert missing.ok is False
    assert "needs a rev" in missing.error


def test_tree_walking_tools_all_honour_gitignore(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root
    (root / "src").mkdir()
    (root / "vendored").mkdir()
    (root / ".gitignore").write_text("vendored/\n")
    run_command(["git", "-C", str(root), "init", "-q"])
    (root / "src" / "real.py").write_text("def real_thing(): pass\n")
    (root / "vendored" / "dep.py").write_text("def vendored_thing(): pass\n")

    symbols = FindSymbol().run(f'{{"roots": ["{root}"]}}', ctx).path.read_text()
    assert "real_thing" in symbols
    assert "vendored_thing" not in symbols

    matches = Ripgrep().run(f'{{"pattern": "thing", "roots": ["{root}"]}}', ctx).path.read_text()
    assert "real.py" in matches
    assert "dep.py" not in matches

    counted = CodeStats().run(f'{{"roots": ["{root}"], "by_file": true}}', ctx).path.read_text()
    assert "real.py" in counted
    assert "dep.py" not in counted

    structural = (
        AstGrep().run(f'{{"pattern": "def $N(): pass", "roots": ["{root}"]}}', ctx).path.read_text()
    )
    assert "real.py" in structural
    assert "dep.py" not in structural


def test_tree_walking_tools_honour_gitignore_outside_a_repository(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root
    (root / "src").mkdir()
    (root / "vendored").mkdir()
    (root / ".gitignore").write_text("vendored/\n")
    (root / "src" / "real.py").write_text("def real_thing(): pass\n")
    (root / "vendored" / "dep.py").write_text("def vendored_thing(): pass\n")
    assert not (root / ".git").exists()

    for text in (
        Ripgrep().run(f'{{"pattern": "thing", "roots": ["{root}"]}}', ctx).path.read_text(),
        FindSymbol().run(f'{{"roots": ["{root}"]}}', ctx).path.read_text(),
        AstGrep()
        .run(f'{{"pattern": "def $N(): pass", "roots": ["{root}"]}}', ctx)
        .path.read_text(),
        CodeStats().run(f'{{"roots": ["{root}"], "by_file": true}}', ctx).path.read_text(),
    ):
        assert "dep.py" not in text
        assert "vendored_thing" not in text
