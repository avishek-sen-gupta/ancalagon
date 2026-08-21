import json
import pathlib

import pydantic
import pytest

import ancalagon.config.config
from ancalagon.attempt.lost import Lost
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.schedule.task_of import task_of
from ancalagon.schedule.uncollected import uncollected
from ancalagon.tools.artifacts.convert_args import ConvertArgs
from ancalagon.tools.artifacts.convert_document import ConvertDocument
from ancalagon.tools.artifacts.document_format import DocumentFormat
from ancalagon.tools.artifacts.extract_strings import ExtractStrings
from ancalagon.tools.artifacts.file_type import FileType
from ancalagon.tools.artifacts.path_arg import PathArg
from ancalagon.tools.artifacts.query_args import QueryArgs
from ancalagon.tools.artifacts.query_json import QueryJson
from ancalagon.tools.artifacts.strings_args import StringsArgs
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate_to import DelegateTo
from ancalagon.tools.delegate.delegate_tools import delegate_tools
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.files.delete_file import DeleteFile
from ancalagon.tools.files.edit_file import EditFile
from ancalagon.tools.files.list_dir import ListDir
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.files.write_file import WriteFile
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.parse.parse_args import ParseArgs
from ancalagon.tools.parse.tree_sitter_tool import TreeSitter
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.ast_grep import AstGrep
from ancalagon.tools.search.find_symbol import FindSymbol
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.ripgrep import Ripgrep
from ancalagon.tools.search.sed import Sed
from ancalagon.tools.search.sed_args import SedArgs
from ancalagon.tools.search.symbol_args import SymbolArgs
from ancalagon.tools.survey.code_stats import CodeStats
from ancalagon.tools.survey.stats_args import StatsArgs
from ancalagon.worker import build_registry
from ancalagon.workspace.workspace import Workspace
from tests.unit.conftest import settle


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
    registry = Registry(
        [
            bind_tool(ReadFile()),
            bind_tool(WriteFile()),
            bind_tool(EditFile()),
            bind_tool(DeleteFile()),
            bind_tool(ListDir()),
        ]
    )

    assert sorted(registry.names()) == [
        "delete_file",
        "edit_file",
        "list_dir",
        "read_file",
        "write_file",
    ]
    assert {s.name for s in registry.schemas()} == set(registry.names())

    target = ctx.workspace.write_root / "note.txt"
    written = registry.get("write_file").invoke(
        f'{{"path": "{target}", "content": "hello world"}}', ctx
    )
    assert written.ok is True
    assert target.read_text() == "hello world"

    read = registry.get("read_file").invoke(f'{{"path": "{target}"}}', ctx)
    assert read.ok is True
    assert read.path.read_text() == "hello world"
    assert read.byte_count == 11

    edited = registry.get("edit_file").invoke(
        f'{{"path": "{target}", "old": "world", "new": "there"}}', ctx
    )
    assert edited.ok is True
    assert target.read_text() == "hello there"

    missing_edit = registry.get("edit_file").invoke(
        f'{{"path": "{target}", "old": "absent", "new": "x"}}', ctx
    )
    assert missing_edit.ok is False
    assert "not found" in missing_edit.error
    assert target.read_text() == "hello there"

    listed = registry.get("list_dir").invoke(f'{{"path": "{ctx.workspace.write_root}"}}', ctx)
    assert listed.ok is True
    assert "note.txt" in listed.path.read_text()

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    denied = registry.get("read_file").invoke(f'{{"path": "{outside}"}}', ctx)
    assert isinstance(denied, ToolResult)
    assert denied.ok is False
    assert "outside" in denied.error

    denied_write = registry.get("write_file").invoke(
        f'{{"path": "{outside}", "content": "x"}}', ctx
    )
    assert denied_write.ok is False
    assert outside.read_text() == "secret"

    deleted = registry.get("delete_file").invoke(f'{{"path": "{target}"}}', ctx)
    assert deleted.ok is True
    assert not target.exists()

    big = ctx.workspace.write_root / "big.txt"
    big.write_text("\n".join(f"line {i}" for i in range(60)))
    first = registry.get("read_file").invoke(f'{{"path": "{big}"}}', ctx)
    assert first.ok is True
    assert first.truncated is True
    assert "line 0" in first.summary.text_for_model()
    assert "of 60" in first.summary.text_for_model()
    shown = int(first.summary.text_for_model().rsplit("offset=", 1)[1].split(" ")[0])
    assert 0 < shown < 60

    rest = registry.get("read_file").invoke(f'{{"path": "{big}", "offset": {shown}}}', ctx)
    assert f"line {shown}" in rest.summary.text_for_model()

    tail = registry.get("read_file").invoke(f'{{"path": "{big}", "offset": 58}}', ctx)
    assert "line 59" in tail.summary.text_for_model()
    assert "end of file" in tail.summary.text_for_model()
    assert tail.truncated is False

    relative = registry.get("read_file").invoke('{"path": "nope.txt"}', ctx)
    assert relative.ok is False
    assert "Relative paths resolve" in relative.error

    absent = registry.get("read_file").invoke(
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
        GrepArgs(pattern="def (alpha|beta)", roots=[ctx.workspace.write_root]), ctx
    )
    assert found.ok is True
    assert [l.split(":", 2)[2].strip() for l in found.path.read_text().splitlines()] == [
        "def alpha():",
        "def beta():",
    ]

    structured = Ripgrep().run(
        GrepArgs(pattern="def alpha", roots=[ctx.workspace.write_root], structured=True), ctx
    )
    matches = [
        r
        for r in (json.loads(line) for line in structured.path.read_text().splitlines())
        if r["type"] == "match"
    ]
    assert str(source) in [m["data"]["path"]["text"] for m in matches]

    missing = Ripgrep().run(GrepArgs(pattern="zzz_absent", roots=[ctx.workspace.write_root]), ctx)
    assert missing.ok is True
    assert missing.path.read_text() == ""

    streamed = Sed().run(SedArgs(script="s/alpha/gamma/", path=source), ctx)
    assert streamed.ok is True
    assert "gamma" in streamed.path.read_text()
    assert source.read_text() == before

    parsed = TreeSitter().run(ParseArgs(path=source, language="python"), ctx)
    assert parsed.ok is True
    assert '"type": "function_definition"' in parsed.path.read_text()

    unsupported = TreeSitter().run(ParseArgs(path=source, language="cobol"), ctx)
    assert unsupported.ok is False
    assert "unsupported language" in unsupported.error

    denied = Sed().run(SedArgs(script="s/a/b/", path=tmp_path / "outside.txt"), ctx)
    assert denied.ok is False

    flags = ctx.workspace.write_root / "flags.txt"
    flags.write_text("a line mentioning --files here\n")

    literal = Ripgrep().run(GrepArgs(pattern="--files", roots=[ctx.workspace.write_root]), ctx)
    assert literal.ok is True
    assert [l.split(":", 2)[2] for l in literal.path.read_text().splitlines()] == [
        "a line mentioning --files here"
    ]

    dashed = Sed().run(SedArgs(script="s/--files/--flags/", path=flags), ctx)
    assert dashed.ok is True
    assert dashed.path.read_text() == "a line mentioning --flags here\n"


def test_registry_withholds_delegate_at_max_depth_and_refuses_unknown_tool_names(
    tmp_path: pathlib.Path,
):
    config = ancalagon.config.config.Config(
        write_root=tmp_path,
        read_roots=(tmp_path,),
        model="claude-opus-5",
        roles={
            "scout": Role(behaviour="Look.", tools=(), budget=Budget(turns=4, tool_calls=8)),
            "unreachable": Role(
                behaviour="Never spawned.",
                input=ClassRef(module=str(tmp_path / "no-such-shapes.py"), name="Query"),
                tools=(),
                budget=Budget(turns=4, tool_calls=8),
            ),
        },
        max_tokens=100,
        num_retries=0,
        request_timeout_s=10,
        max_concurrent_agents=1,
        agent_timeout_s=1,
        max_depth=1,
        summary_chars=100,
        compact_above_tokens=0,
        keep_recent_messages=8,
    )
    migrate_file(tmp_path / "bus.db", latest_version())
    bus = LifecycleStore.open(tmp_path / "bus.db", SystemClock())
    root_agent = bus.enqueue(tmp_path / "root-agent", parent_agent=HUMAN)
    nested_agent = bus.enqueue(tmp_path / "nested-agent", parent_agent=HUMAN)
    full_role = Role(
        behaviour="Coordinate.",
        tools=("delegate_scout", "need_input"),
        budget=Budget(turns=1, tool_calls=1),
    )
    at_root = build_registry(
        config,
        TaskSpec(task_id="root", role=full_role, goal="g"),
        tmp_path,
        parent=root_agent,
        depth=0,
        output_class=FreeText,
        clock=SystemClock(),
    )
    at_limit = build_registry(
        config,
        TaskSpec(task_id="root", role=full_role, goal="g"),
        tmp_path,
        parent=nested_agent,
        depth=1,
        output_class=FreeText,
        clock=SystemClock(),
    )

    assert "delegate_scout" in at_root.names()
    assert "delegate_unreachable" not in at_root.names()
    assert "need_input" in at_root.names()
    assert "delegate_scout" not in at_limit.names()
    assert "need_input" in at_limit.names()
    answer_shape = at_root.get("submit_answer").declaration.parameters.model_json_schema()
    assert set(answer_shape["properties"]) == {"text"}

    narrow_role = Role(behaviour="Search.", tools=("read_file", "ripgrep"), budget=full_role.budget)
    narrowed = build_registry(
        config,
        TaskSpec(task_id="root", role=narrow_role, goal="g"),
        tmp_path,
        parent=root_agent,
        depth=0,
        output_class=FreeText,
        clock=SystemClock(),
    )
    assert set(narrowed.names()) == {"read_file", "ripgrep", "idle", "submit_answer"}

    unknown_role = Role(
        behaviour="Search.",
        tools=("read_file", "rigrep", "grep", "delegate_ghost"),
        budget=full_role.budget,
    )
    with pytest.raises(ValueError) as refused:
        build_registry(
            config,
            TaskSpec(task_id="root", role=unknown_role, goal="g"),
            tmp_path,
            parent=root_agent,
            depth=0,
            output_class=FreeText,
            clock=SystemClock(),
        )
    assert "'delegate_ghost', 'grep', 'rigrep'" in str(refused.value)
    assert "ripgrep" in str(refused.value)


def test_idle_refuses_once_its_children_have_settled(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version())
    bus = LifecycleStore.open(run_dir / "bus.db", FakeClock())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN)
    child = bus.enqueue(run_dir / "tasks" / "c", parent_agent=parent)
    bus.record(child, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(child, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    bus.record(child, AgentStatus.COMPLETED, EventSource.SUPERVISOR)

    idle = bind_tool(Idle(run_dir=run_dir, agent=parent, clock=FakeClock()))
    refused = idle.invoke("{}", _ctx(tmp_path))

    assert refused.ok is False
    assert refused.error == "nothing to wait for: no live children"


def test_delegate_to_refuses_a_live_task_and_retries_a_finished_one(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    role = Role(behaviour="b", tools=(), budget=Budget(turns=3, tool_calls=5))
    delegate = DelegateTo("analyst", role, run_dir, parent=1, clock=SystemClock())
    args = delegate.args_model(task_id="analyse", goal="g", input=FreeText(text="look at this"))
    migrate_file(run_dir / "bus.db", latest_version())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())

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

    bus.record(1, AgentStatus.CRASHED, EventSource.SUPERVISOR, summary="died")
    retried = delegate.run(args, ctx)
    assert retried.ok is True

    task_dir = run_dir / "tasks" / "analyse"
    assert active_for(bus.snapshot(), str(task_dir)) == (2,)
    assert bus.attempt(1) == Lost(close=AgentStatus.CRASHED)
    assert bus.dir_of(2) == str(task_dir)

    written = TaskSpec.model_validate_json((task_dir / "spec.json").read_text())
    assert written.role.behaviour == "b"
    assert written.role.budget == Budget(turns=3, tool_calls=5)
    assert json.loads((task_dir / "spec.json").read_text())["input"] == {"text": "look at this"}

    with pytest.raises(pydantic.ValidationError):
        ClassRef.model_validate({"module": "shape.py", "name": "not a class"})


def test_survey_and_symbol_tools_report_structure_not_mentions(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root
    (root / "widget.py").write_text(
        "class Widget:\n    def spin(self):\n        return 1\n\n\ndef make_widget():\n"
        "    return Widget()\n"
    )
    (root / "user.py").write_text("from widget import Widget\n\nw = Widget()\nw.spin()\n")

    stats = CodeStats().run(StatsArgs(roots=[root]), ctx)
    assert stats.ok is True
    assert "Python" in stats.path.read_text()

    defined = FindSymbol().run(SymbolArgs(roots=[root], name="Widget"), ctx)
    assert defined.ok is True
    lines = [l for l in defined.path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1
    assert "class" in lines[0]
    assert "widget.py" in lines[0]
    assert "user.py" not in defined.path.read_text()

    everything = FindSymbol().run(SymbolArgs(roots=[root]), ctx)
    assert {l.split()[0] for l in everything.path.read_text().splitlines() if l.strip()} >= {
        "Widget",
        "spin",
        "make_widget",
    }

    denied = CodeStats().run(StatsArgs(roots=[tmp_path / "elsewhere"]), ctx)
    assert denied.ok is False


def test_artifact_and_history_tools_read_what_read_file_cannot(tmp_path: pathlib.Path):
    ctx = _ctx(tmp_path)
    root = ctx.workspace.write_root

    binary = root / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02CONNECTION_STRING_HERE\x00\xff" * 3)
    kind = FileType().run(PathArg(path=binary), ctx)
    assert kind.ok is True
    assert kind.summary.text_for_model().strip() != ""

    found = ExtractStrings().run(StringsArgs(path=binary, min_length=8), ctx)
    assert found.ok is True
    assert "CONNECTION_STRING_HERE" in found.path.read_text()

    doc = root / "graph.json"
    doc.write_text('{"nodes": [{"id": "a"}, {"id": "b"}]}')
    ids = QueryJson().run(QueryArgs(path=doc, filter=".nodes[].id"), ctx)
    assert ids.ok is True
    assert ids.path.read_text().split() == ["a", "b"]

    unsafe = QueryJson().run(QueryArgs(path=doc, filter="--version"), ctx)
    assert unsafe.ok is False
    assert "may not begin with" in unsafe.error

    page = root / "note.md"
    page.write_text("# Title\n\nSome *emphasis*.\n")
    converted = ConvertDocument().run(ConvertArgs(path=page, to=DocumentFormat.PLAIN), ctx)
    assert converted.ok is True
    assert "Title" in converted.path.read_text()


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
        Ripgrep().run(GrepArgs(pattern="thing", roots=[root]), ctx).path.read_text(),
        FindSymbol().run(SymbolArgs(roots=[root]), ctx).path.read_text(),
        AstGrep().run(GrepArgs(pattern="def $N(): pass", roots=[root]), ctx).path.read_text(),
        CodeStats().run(StatsArgs(roots=[root], by_file=True), ctx).path.read_text(),
    ):
        assert "dep.py" not in text
        assert "vendored_thing" not in text


def test_collect_task_returns_a_typed_answer_and_explains_every_other_ending(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    migrate_file(run_dir / "bus.db", latest_version())
    role = Role(behaviour="b", tools=(), budget=Budget(turns=20, tool_calls=60))
    delegate = DelegateTo("worker", role, run_dir, parent=1, clock=SystemClock())
    collect = CollectTask(run_dir=run_dir, clock=SystemClock())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())

    def queue(task_id: str) -> int:
        args = delegate.args_model(task_id=task_id, goal="g", input=FreeText(text="go"))
        assert delegate.run(args, ctx).ok is True
        return active_for(bus.snapshot(), str(run_dir / "tasks" / task_id))[0]

    spent = Budget(turns=1, tool_calls=1)
    answered = queue("answered")
    unfinished = queue("unfinished")
    broken = queue("broken")
    asked = queue("asked")

    pending = collect.run(TaskArgs(task=unfinished), ctx)
    assert pending.ok is False
    assert "has not been closed yet" in pending.error

    long_finding = "the finding " * 20
    assert len(long_finding) > ctx.summary_chars
    settle(bus, answered, AgentStatus.COMPLETED)
    (run_dir / "tasks" / "answered" / f"outcome-{answered}.json").write_text(
        Completed[FreeText](
            value=FreeText(text=long_finding), summary="done", spent=spent
        ).model_dump_json()
    )
    got = collect.run(TaskArgs(task=answered), ctx)
    assert got.ok is True
    assert got.truncated is False
    assert json.loads(got.summary.text_for_model()) == {"text": long_finding}
    assert json.loads(got.path.read_text()) == {"text": long_finding}

    haystack = ctx.workspace.write_root / "haystack.txt"
    haystack.write_text("\n".join(f"needle {i}" for i in range(30)) + "\n")
    still_truncates = Ripgrep().run(GrepArgs(pattern="needle", roots=[haystack]), ctx)
    assert still_truncates.ok is True
    assert still_truncates.truncated is True
    assert len(still_truncates.summary.text_for_model()) == ctx.summary_chars

    settle(bus, broken, AgentStatus.FAILED)
    (run_dir / "tasks" / "broken" / f"outcome-{broken}.json").write_text(
        Failed(error="ImportError: no module", summary="died", spent=spent).model_dump_json()
    )
    died = collect.run(TaskArgs(task=broken), ctx)
    assert died.ok is False
    assert "failed" in died.error
    assert "ImportError: no module" in died.error

    settle(bus, asked, AgentStatus.NEEDS_INPUT)
    (run_dir / "tasks" / "asked" / f"outcome-{asked}.json").write_text(
        NeedsInput(question="which caption?", summary="stuck", spent=spent).model_dump_json()
    )
    stuck = collect.run(TaskArgs(task=asked), ctx)
    assert stuck.ok is False
    assert "which caption?" in stuck.error

    parent_task = task_of(bus.snapshot(), answered).id
    child_delegate = DelegateTo("worker", role, run_dir, parent=answered, clock=SystemClock())

    def queue_child(task_id: str) -> int:
        args = child_delegate.args_model(task_id=task_id, goal="g", input=FreeText(text="go"))
        assert child_delegate.run(args, ctx).ok is True
        return active_for(bus.snapshot(), str(run_dir / "tasks" / task_id))[0]

    child = queue_child("child")
    still_running = queue_child("still_running")

    settle(bus, child, AgentStatus.COMPLETED)
    (run_dir / "tasks" / "child" / f"outcome-{child}.json").write_text(
        Completed[FreeText](value=FreeText(text="c"), summary="done", spent=spent).model_dump_json()
    )

    settle(bus, still_running, AgentStatus.IDLING, pid=2)
    (run_dir / "tasks" / "still_running" / f"outcome-{still_running}.json").write_text(
        Completed[FreeText](
            value=FreeText(text="s"), summary="also done", spent=spent
        ).model_dump_json()
    )

    assert uncollected(bus.snapshot(), parent_task) == (child, still_running)
    child_got = collect.run(TaskArgs(task=child), ctx)
    assert child_got.ok is True
    assert AgentStatus.COLLECTED in [e.status for e in bus.history(child)]
    assert uncollected(bus.snapshot(), parent_task) == (still_running,)
    assert active_for(bus.snapshot(), str(run_dir / "tasks" / "child")) == ()

    child_again = collect.run(TaskArgs(task=child), ctx)
    assert child_again.ok is False
    assert child_again.error == f"agent {child} was already collected: ended as completed"
    assert [e.status for e in bus.history(child)].count(AgentStatus.COLLECTED) == 1

    resumed = collect.run(TaskArgs(task=still_running), ctx)
    assert resumed.ok is True
    assert AgentStatus.COLLECTED not in [e.status for e in bus.history(still_running)]

    lost = bus.enqueue(run_dir / "tasks" / "lost", parent_agent=1)
    bus.record(lost, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(lost, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=7)
    bus.record(lost, AgentStatus.TIMED_OUT, EventSource.SUPERVISOR, summary="killed after 600s")
    (run_dir / "tasks" / "lost" / f"outcome-{lost}.json").unlink(missing_ok=True)

    result = CollectTask(run_dir, FakeClock()).run(TaskArgs(task=lost), _ctx(tmp_path))
    assert result.ok is False
    assert result.summary.text_for_model() == "agent 7 ended as timed_out: killed after 600s"
    assert AgentStatus.COLLECTED in [e.status for e in bus.history(lost)]


def test_collect_task_named_by_a_stale_agent_id_records_collected_on_the_newest_agent(
    tmp_path: pathlib.Path,
):
    ctx = _ctx(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    migrate_file(run_dir / "bus.db", latest_version())
    role = Role(behaviour="b", tools=(), budget=Budget(turns=20, tool_calls=60))
    delegate = DelegateTo("worker", role, run_dir, parent=1, clock=SystemClock())
    collect = CollectTask(run_dir=run_dir, clock=SystemClock())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())

    args = delegate.args_model(task_id="resumed", goal="g", input=FreeText(text="go"))
    assert delegate.run(args, ctx).ok is True
    task_dir = run_dir / "tasks" / "resumed"
    first = active_for(bus.snapshot(), str(task_dir))[0]
    settle(bus, first, AgentStatus.IDLING)

    task = task_of(bus.snapshot(), first).id
    second = bus.enqueue(task_dir, parent_agent=1)
    settle(bus, second, AgentStatus.COMPLETED)
    (task_dir / f"outcome-{second}.json").write_text(
        Completed[FreeText](
            value=FreeText(text="resumed answer"),
            summary="done",
            spent=Budget(turns=1, tool_calls=1),
        ).model_dump_json()
    )

    assert newest_agent(bus.snapshot(), task) == second

    result = collect.run(TaskArgs(task=first), ctx)

    assert result.ok is True
    assert [e.status for e in bus.history(second)][-1] == AgentStatus.COLLECTED
    assert AgentStatus.COLLECTED not in [e.status for e in bus.history(first)]


def test_a_delegate_tool_exists_per_role_and_shows_that_role_s_input_schema(
    tmp_path: pathlib.Path,
):
    shapes = tmp_path / "shapes.py"
    shapes.write_text(
        "import pydantic\n\n\nclass Query(pydantic.BaseModel):\n    area: str\n    depth: int\n"
    )
    roles = {
        "analyst": Role(
            behaviour="Analyse.",
            input=ClassRef(module=str(shapes), name="Query"),
            tools=("read_file",),
            budget=Budget(turns=12, tool_calls=30),
        ),
        "scout": Role(
            behaviour="Look.", tools=("read_file",), budget=Budget(turns=4, tool_calls=8)
        ),
    }
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version())

    tools = delegate_tools(roles, run_dir=run_dir, parent=1, clock=FakeClock())

    assert [t.name for t in tools] == ["delegate_analyst", "delegate_scout"]
    shown = tools[0].declaration.parameters.model_json_schema()
    assert sorted(shown["properties"]) == ["goal", "input", "task_id"]
    assert sorted(shown["$defs"]["Query"]["properties"]) == ["area", "depth"]

    ctx = _ctx(tmp_path)
    ok = tools[0].invoke(
        '{"task_id": "t1", "goal": "map the bus", "input": {"area": "bus", "depth": 2}}', ctx
    )
    assert ok.ok is True
    spec = json.loads((run_dir / "tasks" / "t1" / "spec.json").read_text())
    assert spec["goal"] == "map the bus"
    assert spec["input"] == {"area": "bus", "depth": 2}
    assert spec["role"]["budget"] == {"turns": 12, "tool_calls": 30}

    prose = tools[1].declaration.parameters.model_json_schema()
    assert sorted(prose["$defs"]["FreeText"]["properties"]) == ["text"]
    looked = tools[1].invoke(
        '{"task_id": "t3", "goal": "look around", "input": {"text": "start at the bus"}}', ctx
    )
    assert looked.ok is True
    scouted = json.loads((run_dir / "tasks" / "t3" / "spec.json").read_text())
    assert scouted["goal"] == "look around"
    assert scouted["input"] == {"text": "start at the bus"}
    assert scouted["role"]["budget"] == {"turns": 4, "tool_calls": 8}

    with pytest.raises(pydantic.ValidationError, match="depth"):
        tools[0].invoke('{"task_id": "t2", "goal": "g", "input": {"area": "bus"}}', ctx)
    assert (run_dir / "tasks" / "t2").exists() is False
