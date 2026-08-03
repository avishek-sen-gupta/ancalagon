import json
import pathlib

import pydantic

from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
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


def _session(tmp_path: pathlib.Path, replies: list[Reply], budget: Budget) -> Session:
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
        goal="Answer it.",
        output="contracts.py:Verdict",
        budget=budget,
    )
    return Session(
        spec=spec,
        input_json='{"answer": "seed"}',
        messages=[],
        transcript=Transcript(path=tmp_path / "transcript.jsonl", agent_id=17),
        agent_id=17,
        llm=FakeLLM(replies),
        registry=Registry([ReadFile(), NeedInput(), SubmitAnswer(Verdict)]),
        ctx=ctx,
        output_class=Verdict,
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
    assert outcome.spent.tool_calls == 1


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
