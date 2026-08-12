import json
import logging
import pathlib

import pydantic
import pytest

from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.fake_llm import FakeLLM
from ancalagon.session import Session
from ancalagon.tools.files.read_file import ReadFile
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.transcript.transcript import Transcript
from ancalagon.workspace.workspace import Workspace


class Verdict(pydantic.BaseModel):
    answer: str


def _session(
    tmp_path: pathlib.Path,
    replies: list[Reply],
    budget: Budget,
    goal: str = "Answer it.",
    input_json: str = '{"answer": "seed"}',
) -> Session:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    ctx = ToolContext(
        workspace=Workspace(write_root=write_root, read_roots=(write_root,)),
        output_dir=write_root / "outputs",
        summary_chars=200,
        agent_id=17,
    )
    spec = TaskSpec(
        task_id="t1",
        behaviour="You answer questions.",
        goal=goal,
        output="contracts.py:Verdict",
        budget=budget,
    )
    submit = SubmitAnswer(Verdict)
    need_input = NeedInput()
    return Session(
        spec=spec,
        input_json=input_json,
        messages=[],
        transcript=Transcript(path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=FakeLLM(replies),
        registry=Registry([ReadFile(), need_input, submit]),
        ctx=ctx,
        output_class=Verdict,
        submit=submit,
        need_input=need_input,
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
                    ToolUse(
                        id="tu_1",
                        name="read_file",
                        arguments=f'{{"path": "{target / "data.txt"}"}}',
                    )
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[Text(text='Here is my answer.\n\n```json\n{"answer": "payload"}\n```')],
                stop_reason="stop",
            ),
        ],
        Budget(turns=5, tool_calls=5),
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
    ]
    assert [json.loads(line)["seq"] for line in lines] == [0, 1, 2, 3]
    assert all(json.loads(line)["agent"] == 17 for line in lines)
    assert "Answer it." in lines[0]
    assert "read_file" in lines[1]

    second = tmp_path / "second"
    second.mkdir(parents=True, exist_ok=True)
    exhausting = _session(
        second,
        [
            Reply(
                blocks=[ToolUse(id="tu_1", name="read_file", arguments='{"path": "/nope"}')],
                stop_reason="tool_calls",
            ),
            Reply(blocks=[Text(text='{"answer": "best effort"}')], stop_reason="stop"),
        ],
        Budget(turns=1, tool_calls=5),
    )
    forced = exhausting.run()
    assert isinstance(forced, Exhausted)
    assert forced.value.model_dump() == {"answer": "best effort"}


def test_session_returns_tool_failures_and_invalid_output_to_the_agent(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[ToolUse(id="tu_1", name="read_file", arguments='{"path": "/etc/passwd"}')],
                stop_reason="tool_calls",
            ),
            Reply(blocks=[Text(text="not json at all")], stop_reason="stop"),
            Reply(blocks=[Text(text='{"answer": "denied"}')], stop_reason="stop"),
        ],
        Budget(turns=5, tool_calls=5),
    )
    outcome = session.run()
    assert isinstance(outcome, Completed)
    assert outcome.value.model_dump() == {"answer": "denied"}

    transcript = (tmp_path / "transcript.jsonl").read_text()
    assert "outside" in transcript
    assert "did not match the schema" in transcript


def test_session_stops_and_returns_the_question_when_an_agent_needs_input(
    tmp_path: pathlib.Path,
):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUse(
                        id="tu_1",
                        name="need_input",
                        arguments='{"question": "keep both captions or pick one?"}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        Budget(turns=5, tool_calls=5),
    )
    outcome = session.run()
    assert isinstance(outcome, NeedsInput)
    assert outcome.question == "keep both captions or pick one?"
    assert outcome.spent.turns == 1
    assert outcome.spent.tool_calls == 0


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
                    ToolUse(
                        id="tu_1",
                        name="submit_answer",
                        arguments='{"answer": "structured"}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        Budget(turns=5, tool_calls=5),
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
                blocks=[ToolUse(id="tu_1", name="submit_answer", arguments='{"wrong": 1}')],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    ToolUse(id="tu_2", name="submit_answer", arguments='{"answer": "second try"}')
                ],
                stop_reason="tool_calls",
            ),
        ],
        Budget(turns=5, tool_calls=5),
    )
    second = rejected.run()
    assert isinstance(second, Completed)
    assert second.value.model_dump() == {"answer": "second try"}
    assert "did not match the schema" in (tmp_path / "bad" / "transcript.jsonl").read_text()


def test_a_zero_cost_tool_still_works_with_no_tool_call_budget_left(tmp_path: pathlib.Path):
    session = _session(
        tmp_path,
        [
            Reply(
                blocks=[
                    ToolUse(id="tu_1", name="read_file", arguments='{"path": "/nope"}'),
                    ToolUse(id="tu_2", name="read_file", arguments='{"path": "/nope"}'),
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[ToolUse(id="tu_3", name="submit_answer", arguments='{"answer": "free"}')],
                stop_reason="tool_calls",
            ),
        ],
        Budget(turns=5, tool_calls=1),
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
                    ToolUse(
                        id="tu_1",
                        name="submit_answer",
                        arguments='{"answer_json": {"answer": "wrapped by mistake"}}',
                    )
                ],
                stop_reason="tool_calls",
            )
        ],
        Budget(turns=0, tool_calls=5),
    )
    outcome = session.run()

    fake = session.llm
    assert isinstance(fake, FakeLLM)
    assert fake.forced == ["submit_answer"]

    assert isinstance(outcome, Failed)
    assert "wrapped by mistake" in outcome.summary


def test_the_static_system_half_is_shared_across_items_and_the_per_item_half_is_not(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
):
    def answering(item: str, goal: str) -> Session:
        return _session(
            tmp_path / item,
            [
                Reply(
                    blocks=[Text(text='{"answer": "done"}')],
                    stop_reason="stop",
                    cache_creation_input_tokens=2048,
                    cache_read_input_tokens=1024,
                )
            ],
            Budget(turns=5, tool_calls=5),
            goal=goal,
            input_json=f'{{"answer": "{item}"}}',
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
    assert '"answer": "item-0001"' in per_item
    assert str(tmp_path / "item-0001" / "ws") in per_item

    assert "cache created 2048 read 1024" in caplog.text
