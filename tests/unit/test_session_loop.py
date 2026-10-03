import collections.abc
import json
import logging
import pathlib

import pydantic
import pytest

from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.bus.no_bus import NO_BUS
from ancalagon.children.bus_children import BusChildren
from ancalagon.children.children import Children
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.config.config import Config
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.answer_file import AnswerFile
from ancalagon.contracts.answer_status import AnswerStatus
from ancalagon.contracts.call_usage import CallUsage
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.idling import Idling
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.no_watermark import NO_WATERMARK
from ancalagon.contracts.outcome_kind import OutcomeKind
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.reviewed import Reviewed
from ancalagon.contracts.serialisable_role import SerialisableBudget, SerialisableRole
from ancalagon.contracts.spend import Spend
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_schema import ToolSchema
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use_from_model import ToolUseFromModel
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.letterbox.letterbox import Letterbox
from ancalagon.letterbox.no_letterbox import NO_LETTERBOX
from ancalagon.llm.fake_llm import FakeLLM
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.session import COLLECT_TRIES, NOTE_PREFIX, Session
from ancalagon.session_for import assemble
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.no_idle import NoIdle
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.submit.submit_answer_as_file import SubmitAnswerAsFile
from ancalagon.transcript.transcript import Transcript
from ancalagon.web.fake_web_client import FakeWebClient
from ancalagon.workspace.workspace import Workspace
from ancalagon.profiles.answering import ANSWERING, Answering
from ancalagon.profiles.catalogue import Catalogue
from ancalagon.profiles.profile import Profile
from ancalagon.profiles.standing import MECHANICS, STANDING, Standing
from ancalagon.profiles.answering_as_file import ANSWERING_AS_FILE, AnsweringAsFile
from tests.unit.conftest import written_budget


class Verdict(pydantic.BaseModel):
    answer: str


class Where(pydantic.BaseModel):
    path: str


class Values(pydantic.BaseModel, frozen=True):
    values: tuple[int, ...]


class Sited(pydantic.BaseModel):
    answer: str
    where: Where


def _forced(llm: FakeLLM) -> list[str]:
    return [f.name if isinstance(f, ToolSchema) else "" for f in llm.forced]


def _profile(
    tools: collections.abc.Sequence[BoundTool],
    output_class: type[pydantic.BaseModel],
    kind: type[Profile] = Answering,
) -> Profile:
    held = {bound.spec.source for bound in tools}
    spares = [
        bound
        for source, bound in (
            (SubmitAnswer, lambda: bind_tool(SubmitAnswer(output_class))),
            (CollectTask, lambda: bind_tool(CollectTask(NO_BUS, RealFileSystem()))),
            (NoIdle, lambda: bind_tool(NoIdle())),
        )
        if source not in held
        for bound in [bound()]
    ]
    return kind(Catalogue([*tools, *spares]))


def _session(
    tmp_path: pathlib.Path,
    replies: list[Reply],
    budget: SerialisableBudget,
    goal: str = "Answer it.",
    given: pydantic.BaseModel = Verdict(answer="seed"),
    answer_class: type[pydantic.BaseModel] = Verdict,
    letterbox: Letterbox = NO_LETTERBOX,
    extra_write_roots: tuple[pathlib.PurePath, ...] = (),
) -> Session:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(
            RealFileSystem(),
            write_roots=(write_root, *extra_write_roots),
            read_roots=(write_root,),
        ),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = TaskSpec(
        task_id="t1",
        role=SerialisableRole(
            profile=ANSWERING,
            behaviour="You answer questions.",
            answer=ClassRef(module="verdict.py", name="Verdict"),
            tools=(),
            budget=budget,
        ),
        goal=goal,
    )
    tools = [
        bind_tool(ReadFile(FakeClock())),
        bind_tool(NeedInput()),
        bind_tool(SubmitAnswer(answer_class)),
    ]
    return Session(
        spec=spec,
        input=given,
        messages=[],
        transcript=Transcript(RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=FakeLLM(replies),
        registry=Registry(tools),
        profile=_profile(tools, answer_class),
        ctx=ctx,
        output_class=answer_class,
        clock=FakeClock(),
        letterbox=letterbox,
    )


def test_session_runs_tools_completes_and_forces_a_final_answer_when_exhausted(
    tmp_path: pathlib.Path,
):
    target = tmp_path / "ws"
    target.mkdir(parents=True, exist_ok=True)
    (target / "data.txt").write_text("payload")

    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="read_file",
                        arguments=f'{{"path": "{target / "data.txt"}"}}',
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2", name="submit_answer", arguments='{"answer": "payload"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.model_dump() == {"answer": "payload"}
    assert outcome.spent.turns == 2
    assert outcome.spent.tool_calls == 1

    lines = (tmp_path / "transcript.jsonl").read_text().splitlines()
    assert [json.loads(line)["role"] for line in lines] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert [json.loads(line)["seq"] for line in lines] == [0, 1, 2, 3, 4]
    assert all(json.loads(line)["agent"] == 17 for line in lines)
    assert all(json.loads(line)["ts"] == "2026-01-01T00:00:00+00:00" for line in lines)
    assert "Answer it." in lines[0]
    assert "read_file" in lines[1]

    returned = json.loads(lines[2])["blocks"][0]["content"]
    assert returned.startswith("1\tpayload\n[lines 1-1 of 1; end of file]\n[full output: ")

    second = tmp_path / "second"
    second.mkdir(parents=True, exist_ok=True)
    exhausting = _session(
        second,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(id="tu_1", name="read_file", arguments='{"path": "/nope"}')
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2", name="submit_answer", arguments='{"answer": "best effort"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(1, 5),
    )
    forced = exhausting.run()
    assert isinstance(forced, Exhausted)
    assert forced.value.model_dump() == {"answer": "best effort"}

    told = exhausting.llm
    assert isinstance(told, FakeLLM)
    assert [b.text for b in told.seen[-1][-1].blocks if isinstance(b, Text)] == [
        "Your budget is exhausted. Answer now from what you already know, "
        "using the submit_answer tool. No other tools are available."
    ]


def test_session_returns_tool_failures_and_nudges_a_reply_that_called_nothing(
    tmp_path: pathlib.Path,
):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1", name="read_file", arguments='{"path": "/etc/passwd"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(blocks=[Text(text='Here it is: {"answer": "denied"}')], stop_reason="stop"),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2", name="submit_answer", arguments='{"answer": "denied"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.model_dump() == {"answer": "denied"}
    assert outcome.spent.turns == 3

    transcript = (tmp_path / "transcript.jsonl").read_text()
    assert "outside" in transcript

    absent = _session(
        tmp_path / "absent",
        [
            Reply(
                blocks=[ToolUseFromModel(id="tu_x", name="telepathy", arguments="{}")],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_y", name="submit_answer", arguments='{"answer": "no such tool"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 5),
    )
    settled = absent.run()
    assert isinstance(settled, Completed)
    assert settled.value.model_dump() == {"answer": "no such tool"}
    refused = [
        block
        for message in absent.messages
        for block in message.blocks
        if isinstance(block, ToolResultBlock) and block.tool_use_id == "tu_x"
    ]
    assert [(b.is_error, b.content) for b in refused] == [(True, "unknown tool telepathy")]
    assert settled.spent.tool_calls == 0
    assert "Answers are only accepted through the submit_answer tool" in transcript


def test_session_stops_and_returns_the_question_when_an_agent_needs_input(
    tmp_path: pathlib.Path,
):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="need_input",
                        arguments='{"question": "keep both captions or pick one?"}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        written_budget(5, 5),
    )
    outcome = session.run()
    assert isinstance(outcome, NeedsInput)
    assert outcome.question == "keep both captions or pick one?"
    assert outcome.spent.turns == 1
    assert outcome.spent.tool_calls == 0


def test_session_stops_and_returns_idling_when_the_agent_idles(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", FakeClock(), RealFileSystem())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN).id
    child = bus.enqueue(run_dir / "tasks" / "c", parent_agent=parent).id

    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=parent,
    )
    spec = TaskSpec(
        task_id="t1",
        role=SerialisableRole(
            profile=ANSWERING,
            behaviour="You answer questions.",
            answer=ClassRef(module="verdict.py", name="Verdict"),
            tools=(),
            budget=written_budget(5, 5),
        ),
        goal="Answer it.",
    )
    idle_only = [bind_tool(Idle(bus, agent=parent))]
    session = Session(
        spec=spec,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(
            RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=parent
        ),
        agent_id=parent,
        llm=FakeLLM(
            [
                Reply(
                    blocks=[ToolUseFromModel(id="tu_1", name="idle", arguments="{}")],
                    stop_reason="tool_calls",
                )
            ]
        ),
        registry=Registry(idle_only),
        profile=_profile(idle_only, Verdict),
        ctx=ctx,
        output_class=Verdict,
        clock=FakeClock(),
    )
    outcome = session.run()

    assert isinstance(outcome, Idling)
    assert outcome.kind == OutcomeKind.IDLING.value
    assert outcome.summary == f"idling until one of agents [{child}] finishes"
    assert outcome.spent == Spend(turns=1, tool_calls=0)
    highest = max(e.id for events in bus.snapshot().events.values() for e in events)
    assert outcome.seen_through == highest


def test_exhausting_turns_with_live_children_idles_rather_than_forcing_an_answer(
    tmp_path: pathlib.Path,
):
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", FakeClock(), RealFileSystem())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN).id
    bus.enqueue(run_dir / "tasks" / "c", parent_agent=parent)

    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=parent,
    )
    spec = TaskSpec(
        task_id="t1",
        role=SerialisableRole(
            profile=ANSWERING,
            behaviour="You answer questions.",
            answer=ClassRef(module="verdict.py", name="Verdict"),
            tools=(),
            budget=written_budget(1, 5),
        ),
        goal="Answer it.",
    )
    reading_and_idle = [
        bind_tool(ReadFile(FakeClock())),
        bind_tool(Idle(bus, agent=parent)),
    ]
    session = Session(
        spec=spec,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(
            RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=parent
        ),
        agent_id=parent,
        llm=FakeLLM([Reply(blocks=[Text(text="not json at all")], stop_reason="stop")]),
        registry=Registry(reading_and_idle),
        profile=_profile(reading_and_idle, Verdict),
        ctx=ctx,
        output_class=Verdict,
        clock=FakeClock(),
        children=BusChildren(bus, parent),
    )
    outcome = session.run()

    assert outcome.kind == OutcomeKind.IDLING.value
    assert outcome.spent == Spend(turns=1, tool_calls=0)
    assert isinstance(outcome, Idling)
    assert outcome.seen_through == NO_WATERMARK


def test_submit_answer_description_states_the_answer_shape():
    described = SubmitAnswer(Verdict).description
    assert "answer" in described
    assert '{"answer": "..."}' in described
    assert "Do not wrap" in described


def test_session_completes_from_a_submit_answer_tool_call(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="submit_answer",
                        arguments='{"answer": "structured"}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        written_budget(5, 5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.model_dump() == {"answer": "structured"}
    assert outcome.spent.turns == 1
    assert outcome.spent.tool_calls == 0

    rejected = _session(
        tmp_path / "bad",
        [
            Reply(
                blocks=[
                    ToolUseFromModel(id="tu_1", name="submit_answer", arguments='{"wrong": 1}')
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2", name="submit_answer", arguments='{"answer": "second try"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 5),
    )
    second = rejected.run()
    assert isinstance(second, Completed)
    assert second.value.model_dump() == {"answer": "second try"}
    refusal = (tmp_path / "bad" / "transcript.jsonl").read_text()
    assert "submit_answer arguments are invalid:" in refusal
    assert "answer: Field required" in refusal
    assert "input_value" not in refusal


def test_a_zero_cost_tool_still_works_with_no_tool_call_budget_left(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(id="tu_1", name="read_file", arguments='{"path": "/nope"}'),
                    ToolUseFromModel(id="tu_2", name="read_file", arguments='{"path": "/nope"}'),
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_3", name="submit_answer", arguments='{"answer": "free"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 1),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.model_dump() == {"answer": "free"}
    assert outcome.spent.tool_calls == 1

    transcript = (tmp_path / "transcript.jsonl").read_text()
    assert "budget exhausted" in transcript


def test_final_turn_forces_submit_answer_and_keeps_a_rejected_payload(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="submit_answer",
                        arguments='{"answer_json": {"answer": "wrapped by mistake"}}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        written_budget(0, 5),
    )
    outcome = session.run()

    fake = session.llm
    assert isinstance(fake, FakeLLM)
    assert _forced(fake) == ["submit_answer"]

    assert isinstance(outcome, Failed)
    assert "wrapped by mistake" in outcome.summary


class ScriptedLetterbox(Letterbox):
    def __init__(self, notes: collections.abc.Sequence[tuple[str, ...]]):
        self._notes = list(notes)
        self.marked: list[int] = []

    def unread(self) -> tuple[str, ...]:
        if not self._notes:
            return ()
        head, *rest = self._notes
        self._notes = rest
        return head

    def mark(self, delivered: int) -> None:
        self.marked = [*self.marked, delivered]


def test_a_note_left_for_a_task_joins_the_next_turn_and_costs_no_turn(tmp_path: pathlib.Path):
    box = ScriptedLetterbox([("pass the nested fields as objects",)])
    session = _session(
        tmp_path,
        [
            Reply(blocks=[Text(text="still looking")], stop_reason="stop"),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1", name="submit_answer", arguments='{"answer": "done"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        written_budget(5, 5),
        letterbox=box,
    )
    outcome = session.run()

    fake = session.llm
    assert isinstance(fake, FakeLLM)
    delivered = f"{NOTE_PREFIX}pass the nested fields as objects"

    def texts(turn: int) -> list[str]:
        return [b.text for m in fake.seen[turn] for b in m.blocks if isinstance(b, Text)]

    assert delivered in texts(0)
    assert delivered in texts(1)
    assert box.marked == [1, 0]

    assert isinstance(outcome, Completed)
    assert outcome.spent == Spend(turns=2, tool_calls=0)
    transcript = (tmp_path / "transcript.jsonl").read_text()
    assert delivered in transcript
    assert "Noted. Carry on, and call the submit_answer tool when you have your answer." in texts(1)
    assert "Answers are only accepted" not in transcript


def test_the_answer_schema_named_in_the_system_prompt_carries_no_references(
    tmp_path: pathlib.Path,
):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="submit_answer",
                        arguments='{"answer": "done", "where": {"path": "/tmp/x"}}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        written_budget(5, 5),
        answer_class=Sited,
    )
    outcome = session.run()

    fake = session.llm
    assert isinstance(fake, FakeLLM)
    static = fake.systems[0].static
    assert "$ref" not in static
    assert "$defs" not in static
    assert "'where': {'properties': {'path': {'title': 'Path', 'type': 'string'}}" in static

    assert isinstance(outcome, Completed)
    assert outcome.value == Sited(answer="done", where=Where(path="/tmp/x"))


def test_the_static_system_half_is_shared_across_items_and_the_per_item_half_is_not(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    def answering(item: str, goal: str) -> Session:
        return _session(
            tmp_path / item,
            [
                Reply(
                    blocks=[
                        ToolUseFromModel(
                            id="tu_1", name="submit_answer", arguments='{"answer": "done"}'
                        )
                    ],
                    stop_reason="tool_calls",
                    usage=CallUsage(cache_creation_tokens=2048, cache_read_tokens=1024),
                )
            ],
            written_budget(5, 5),
            goal=goal,
            given=Verdict(answer=item),
            extra_write_roots=(tmp_path / item / "notes",),
        )

    first = answering("item-0001", "Describe the first item.")
    second = answering("item-0002", "Describe the second item.")
    with caplog.at_level(logging.INFO, logger="ancalagon.session"):
        first.run()
    second.run()

    one, two = first.llm, second.llm
    assert isinstance(one, FakeLLM)
    assert isinstance(two, FakeLLM)

    static, per_item = one.systems[0].static, one.systems[0].per_item
    assert static == two.systems[0].static
    assert static.startswith("You answer questions.")
    assert "submit_answer" in static
    assert "Goal:" not in static
    assert "You may write under" not in static

    assert per_item != two.systems[0].per_item
    assert per_item.startswith("Goal: Describe the first item.")
    assert '"answer":"item-0001"' in per_item
    assert str(tmp_path / "item-0001" / "ws") in per_item
    assert str(tmp_path / "item-0001" / "notes") in per_item

    assert "cache created 2048 read 1024" in caplog.text


def test_a_session_takes_its_behaviour_and_budget_from_its_role(tmp_path: pathlib.Path):
    role = SerialisableRole(
        profile=ANSWERING,
        behaviour="You investigate.",
        tools=("read_file",),
        budget=written_budget(2, 4),
    )
    spec = TaskSpec(task_id="t", role=role, goal="find it")
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    llm = FakeLLM(
        [
            Reply(
                blocks=[ToolUseFromModel(id="tu_1", name="unknown_tool", arguments="{}")],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[ToolUseFromModel(id="tu_2", name="unknown_tool", arguments="{}")],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_3", name="submit_answer", arguments='{"text": "found it"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ]
    )
    submit_only = [bind_tool(SubmitAnswer(FreeText))]
    session = Session(
        spec=spec,
        input=FreeText(text="go"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=llm,
        registry=Registry(submit_only),
        profile=_profile(submit_only, FreeText),
        ctx=ctx,
        output_class=FreeText,
        clock=FakeClock(),
    )
    outcome = session.run()

    assert llm.systems[0].static.startswith("You investigate.")
    assert outcome.spent == Spend(turns=2, tool_calls=0)


class ScriptedChildren(Children):
    def __init__(
        self,
        outstanding: collections.abc.Sequence[tuple[int, ...]],
        uncollected: collections.abc.Sequence[tuple[int, ...]],
    ):
        self._outstanding = list(outstanding)
        self._uncollected = list(uncollected)
        self._last_outstanding: tuple[int, ...] = ()
        self._last_uncollected: tuple[int, ...] = ()

    def outstanding(self) -> tuple[int, ...]:
        if self._outstanding:
            self._last_outstanding = self._outstanding[0]
            self._outstanding = self._outstanding[1:]
        return self._last_outstanding

    def uncollected(self) -> tuple[int, ...]:
        if self._uncollected:
            self._last_uncollected = self._uncollected[0]
            self._uncollected = self._uncollected[1:]
        return self._last_uncollected


def test_a_session_narrows_each_turn_and_the_last_turn_is_an_ordinary_one(
    tmp_path: pathlib.Path,
):
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    (write_root / "data.txt").write_text("payload")

    children = ScriptedChildren([(2,), ()], [(), (2,), ()])
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = TaskSpec(
        task_id="t1",
        role=SerialisableRole(
            profile=ANSWERING,
            behaviour="You answer questions.",
            answer=ClassRef(module="verdict.py", name="Verdict"),
            tools=(),
            budget=written_budget(2, 5),
        ),
        goal="Answer it.",
    )
    llm = FakeLLM(
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1",
                        name="read_file",
                        arguments=f'{{"path": "{write_root / "data.txt"}"}}',
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2",
                        name="read_file",
                        arguments=f'{{"path": "{write_root / "data.txt"}"}}',
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_3", name="submit_answer", arguments='{"answer": "done"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ]
    )
    full_set = [
        bind_tool(ReadFile(FakeClock())),
        bind_tool(Idle(NO_BUS, agent=17)),
        bind_tool(SubmitAnswer(Verdict)),
        bind_tool(CollectTask(NO_BUS, RealFileSystem())),
    ]
    session = Session(
        spec=spec,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=llm,
        registry=Registry(full_set),
        profile=_profile(full_set, Verdict),
        ctx=ctx,
        output_class=Verdict,
        clock=FakeClock(),
        children=children,
    )

    outcome = session.run()

    assert [sorted(s.name for s in seen) for seen in llm.offered] == [
        ["collect_task", "idle", "read_file"],
        ["collect_task", "read_file"],
        ["submit_answer"],
    ]
    assert outcome.kind == OutcomeKind.EXHAUSTED.value


def test_a_hook_gates_every_answer_and_prose_cannot_evade_it(tmp_path: pathlib.Path):
    def always_refuses(args: pydantic.BaseModel, ctx: ToolContext) -> Reviewed:
        return Refused(reason="every answer must cite a file")

    submitting = Reply(
        blocks=[
            ToolUseFromModel(id="s1", name="submit_answer", arguments='{"answer": "no citation"}')
        ],
        stop_reason="tool_calls",
    )
    session = _session(tmp_path, [submitting] * 4, written_budget(2, 4))
    session.registry = Registry([bind_tool(SubmitAnswer(Verdict), before=always_refuses)])

    outcome = session.run()

    assert isinstance(outcome, Failed)
    assert outcome.error == "submit_answer refused: every answer must cite a file"
    assert outcome.summary == '{"answer": "no citation"}'
    assert outcome.spent == Spend(turns=2, tool_calls=0)

    prose = Reply(blocks=[Text(text='{"answer": "no citation"}')], stop_reason="stop")
    evading = _session(tmp_path / "prose", [prose] * 3, written_budget(2, 4))
    evading.registry = Registry([bind_tool(SubmitAnswer(Verdict), before=always_refuses)])

    evaded = evading.run()

    assert isinstance(evaded, Failed)
    assert evaded.error == "no final answer"
    assert evaded.summary == '{"answer": "no citation"}'
    assert evaded.spent == Spend(turns=2, tool_calls=0)

    nudged = (tmp_path / "prose" / "transcript.jsonl").read_text()
    assert "Answers are only accepted through the submit_answer tool" in nudged


def test_the_final_turn_forces_whichever_submit_tool_the_role_named(tmp_path: pathlib.Path):
    answer = tmp_path / "ws" / "record.json"
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    answer.write_text('{"values": []}')
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = TaskSpec(
        task_id="t1",
        role=SerialisableRole(
            profile=ANSWERING_AS_FILE,
            behaviour="You answer questions.",
            answer=ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile"),
            tools=("submit_answer_as_file",),
            budget=written_budget(0, 4),
        ),
        goal="Answer it.",
    )
    arguments = json.dumps({"status": "complete", "summary": "one record", "path": str(answer)})
    llm = FakeLLM(
        [
            Reply(
                blocks=[
                    ToolUseFromModel(id="s1", name="submit_answer_as_file", arguments=arguments)
                ],
                stop_reason="tool_calls",
            )
        ]
    )
    as_file_only = [bind_tool(SubmitAnswerAsFile(Values))]
    session = Session(
        spec=spec,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=llm,
        registry=Registry(as_file_only),
        profile=_profile(as_file_only, AnswerFile, AnsweringAsFile),
        ctx=ctx,
        output_class=AnswerFile,
        clock=FakeClock(),
    )

    outcome = session.run()

    assert _forced(llm) == ["submit_answer_as_file"]
    assert [sorted(s.name for s in seen) for seen in llm.offered] == [["submit_answer_as_file"]]
    assert isinstance(outcome, Exhausted)
    assert outcome.value == AnswerFile(
        status=AnswerStatus.COMPLETE, summary="one record", path=pathlib.PurePath(answer)
    )

    both = tmp_path / "both"
    both.mkdir(parents=True, exist_ok=True)
    answer_both = both / "record.json"
    answer_both.write_text('{"values": []}')
    ctx_both = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(both,), read_roots=(both,)),
        task_dir=both / "outputs",
        summary_chars=200,
        agent_id=18,
    )
    role_both = SerialisableRole(
        profile=ANSWERING_AS_FILE,
        behaviour="You answer questions.",
        answer=ClassRef(module="ancalagon.contracts.answer_file", name="AnswerFile"),
        answer_file=ClassRef(module=__name__, name="Values"),
        tools=("submit_answer", "submit_answer_as_file"),
        budget=written_budget(2, 4),
    )
    spec_both = TaskSpec(
        task_id="t2",
        role=role_both,
        goal="Answer it.",
    )
    config_both = Config(
        home=both,
        read_roots=(),
        model="anthropic/claude",
        roles={"t2": role_both},
    )
    assembled_both = assemble(
        config_both,
        spec_both,
        both,
        parent=0,
        depth=0,
        output_class=AnswerFile,
        answer_file_class=Values,
        clock=FakeClock(),
        fs=RealFileSystem(),
        web=FakeWebClient({}),
        bus=NO_BUS,
    )
    arguments_both = json.dumps(
        {"status": "complete", "summary": "one record", "path": str(answer_both)}
    )
    llm_both = FakeLLM(
        [
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="s1", name="submit_answer_as_file", arguments=arguments_both
                    )
                ],
                stop_reason="tool_calls",
            )
        ]
    )
    session_both = Session(
        spec=spec_both,
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=both / "transcript.jsonl", agent_id=18),
        agent_id=18,
        llm=llm_both,
        registry=assembled_both.registry,
        profile=assembled_both.profile,
        ctx=ctx_both,
        output_class=AnswerFile,
        clock=FakeClock(),
    )

    outcome_both = session_both.run()

    offered_names = [sorted(s.name for s in seen) for seen in llm_both.offered]
    assert offered_names == [["submit_answer_as_file"]]
    assert "submit_answer" not in offered_names[0]
    assert isinstance(outcome_both, Completed)


def test_a_session_whose_provider_dies_returns_a_failure_carrying_what_it_spent(
    tmp_path: pathlib.Path,
):
    session = _session(tmp_path, [], written_budget(5, 5))

    outcome = session.run()

    assert isinstance(outcome, Failed)
    assert "RuntimeError" in outcome.error
    assert "FakeLLM exhausted" in outcome.error
    assert "Traceback (most recent call last)" in outcome.error
    assert outcome.summary == "FakeLLM exhausted"
    assert outcome.spent == Spend(turns=1, tool_calls=0)


def _collectable_child(bus: LifecycleStore, run_dir: pathlib.Path, parent: int, text: str) -> int:
    child_dir = run_dir / "tasks" / "c1"
    child_dir.mkdir(parents=True)
    child = bus.enqueue(child_dir, parent_agent=parent).id
    (child_dir / "spec.json").write_text(
        TaskSpec(
            task_id="c1",
            role=SerialisableRole(
                profile=ANSWERING,
                behaviour="Investigate.",
                answer=ClassRef(module="ancalagon.contracts.free_text", name="FreeText"),
                tools=("submit_answer",),
                budget=written_budget(2, 2),
            ),
            goal="Look at it.",
        ).model_dump_json()
    )
    (child_dir / f"outcome-{child}.json").write_text(
        Completed(
            value=FreeText(text=text), summary=text, spent=Spend(turns=1, tool_calls=1)
        ).model_dump_json()
    )
    bus.record(child, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(child, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=2)
    bus.record(child, AgentStatus.COMPLETED, EventSource.SUPERVISOR, summary=text)
    return child


def _staged_bus(run_dir: pathlib.Path) -> tuple[LifecycleStore, int, int]:
    (run_dir / "tasks").mkdir(parents=True, exist_ok=True)
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", FakeClock(), RealFileSystem())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN).id
    bus.record(parent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(parent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    child = _collectable_child(bus, run_dir, parent, "the child found it")
    return bus, parent, child


def _exhausted_parent(
    tmp_path: pathlib.Path,
    run_dir: pathlib.Path,
    bus: LifecycleStore,
    parent: int,
    replies: list[Reply],
    with_collect: bool = True,
) -> Session:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=parent,
    )
    maybe_collecting = [bind_tool(ReadFile(FakeClock())), bind_tool(SubmitAnswer(Verdict))] + (
        [bind_tool(CollectTask(bus, RealFileSystem()))] if with_collect else []
    )
    return Session(
        spec=TaskSpec(
            task_id="root",
            role=SerialisableRole(
                profile=ANSWERING,
                behaviour="You coordinate.",
                answer=ClassRef(module="verdict.py", name="Verdict"),
                tools=(),
                budget=written_budget(1, 0),
            ),
            goal="Answer it.",
        ),
        input=Verdict(answer="seed"),
        messages=[],
        transcript=Transcript(RealFileSystem(), path=run_dir / "transcript.jsonl", agent_id=parent),
        agent_id=parent,
        llm=FakeLLM(replies),
        registry=Registry(maybe_collecting),
        profile=_profile(maybe_collecting, Verdict),
        ctx=ctx,
        output_class=Verdict,
        clock=FakeClock(),
        children=BusChildren(bus, parent),
    )


def test_the_final_turn_collects_every_answer_before_one_is_forced(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    bus, parent, child = _staged_bus(run_dir)
    session = _exhausted_parent(
        tmp_path,
        run_dir,
        bus,
        parent,
        [
            Reply(blocks=[Text(text="still thinking")], stop_reason="stop"),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_1", name="collect_task", arguments=json.dumps({"task": child})
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_2", name="submit_answer", arguments='{"answer": "combined"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
    )
    outcome = session.run()
    llm = session.llm
    assert isinstance(llm, FakeLLM)

    assert [sorted(t.name for t in offered) for offered in llm.offered] == [
        ["collect_task", "read_file"],
        ["collect_task"],
        ["submit_answer"],
    ]
    assert _forced(llm) == ["", "collect_task", "submit_answer"]
    assert isinstance(outcome, Exhausted)
    assert outcome.value.model_dump() == {"answer": "combined"}
    assert BusChildren(bus, parent).uncollected() == ()
    assert outcome.spent.tool_calls == 0


def test_a_forced_collect_that_never_lands_gives_up_and_answers_anyway(tmp_path: pathlib.Path):
    run_dir = tmp_path / "run"
    bus, parent, child = _staged_bus(run_dir)
    missing = json.dumps({"task": 999})
    session = _exhausted_parent(
        tmp_path,
        run_dir,
        bus,
        parent,
        [
            Reply(blocks=[Text(text="still thinking")], stop_reason="stop"),
            *[
                Reply(
                    blocks=[ToolUseFromModel(id=f"tu_{n}", name="collect_task", arguments=missing)],
                    stop_reason="tool_calls",
                )
                for n in range(COLLECT_TRIES)
            ],
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_z", name="submit_answer", arguments='{"answer": "gave up"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
    )
    outcome = session.run()
    llm = session.llm
    assert isinstance(llm, FakeLLM)

    assert _forced(llm) == ["", *["collect_task"] * COLLECT_TRIES, "submit_answer"]
    assert isinstance(outcome, Exhausted)
    assert outcome.value.model_dump() == {"answer": "gave up"}
    assert BusChildren(bus, parent).uncollected() == (child,)

    bare_dir = tmp_path / "bare"
    bare_bus, bare_parent, bare_child = _staged_bus(bare_dir)
    bare = _exhausted_parent(
        tmp_path / "bare_ws",
        bare_dir,
        bare_bus,
        bare_parent,
        [
            Reply(blocks=[Text(text="still thinking")], stop_reason="stop"),
            Reply(
                blocks=[
                    ToolUseFromModel(
                        id="tu_b", name="submit_answer", arguments='{"answer": "no collect"}'
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
        with_collect=False,
    )
    bare_outcome = bare.run()
    bare_llm = bare.llm
    assert isinstance(bare_llm, FakeLLM)
    assert _forced(bare_llm) == ["", "submit_answer"]
    assert isinstance(bare_outcome, Exhausted)
    assert bare_outcome.value.model_dump() == {"answer": "no collect"}
    assert BusChildren(bare_bus, bare_parent).uncollected() == (bare_child,)


def test_a_standing_session_runs_out_of_turns_without_being_told_to_answer(
    tmp_path: pathlib.Path,
):
    run_dir = tmp_path / "run"
    (run_dir / "tasks").mkdir(parents=True)
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", FakeClock(), RealFileSystem())
    parent = bus.enqueue(run_dir / "tasks" / "root", parent_agent=HUMAN).id

    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(RealFileSystem(), write_roots=(write_root,), read_roots=(write_root,)),
        task_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=parent,
    )
    tools = [bind_tool(ReadFile(FakeClock())), bind_tool(Idle(bus, agent=parent))]
    llm = FakeLLM(
        [
            Reply(
                blocks=[ToolUseFromModel(id="i1", name="idle", arguments="{}")],
                stop_reason="tool_calls",
            )
        ]
    )
    session = Session(
        spec=TaskSpec(
            task_id="t1",
            role=SerialisableRole(
                profile=STANDING,
                behaviour="You stand by.",
                tools=("read_file",),
                budget=written_budget(0, 4),
            ),
            goal="Keep a note.",
        ),
        input=FreeText(text="go"),
        messages=[],
        transcript=Transcript(
            RealFileSystem(), path=tmp_path / "transcript.jsonl", agent_id=parent
        ),
        agent_id=parent,
        llm=llm,
        registry=Registry(tools),
        profile=Standing(Catalogue(tools)),
        ctx=ctx,
        output_class=FreeText,
        clock=FakeClock(),
        children=BusChildren(bus, parent),
    )

    outcome = session.run()

    assert isinstance(outcome, Idling)
    # The turn budget was already spent, and nothing told it to answer: it never was going to.
    said = [b.text for m in llm.seen[-1] for b in m.blocks if isinstance(b, Text)]
    assert said == ['Keep a note.\n\nInput: {"text":"go"}']
    assert _forced(llm) == [""]
    assert sorted(s.name for s in llm.offered[0]) == ["idle", "read_file"]
    assert llm.systems[0].static == f"You stand by.\n\n{MECHANICS}"
