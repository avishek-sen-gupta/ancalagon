import collections.abc
import json
import pathlib

import pytest

from ancalagon.answer_command import answer_command
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.free_text import FreeText
from ancalagon.contracts.message import Message
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import Outcome
from ancalagon.contracts.reply import Reply
from ancalagon.contracts.role import Role
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.text import Text
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.llm.fake_llm import FakeLLM
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.schedule.active_for import active_for
from ancalagon.session import Session
from ancalagon.tools.delegate.answer_task import AnswerTask
from ancalagon.tools.delegate.check_task import CheckTask
from ancalagon.tools.delegate.collect_task import CollectTask
from ancalagon.tools.delegate.delegate_tools import delegate_tools
from ancalagon.tools.need_input.need_input import NeedInput
from ancalagon.tools.registry.bind_tool import bind_tool
from ancalagon.tools.registry.registry import Registry
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.submit.submit_answer import SubmitAnswer
from ancalagon.transcript.history import load, repair
from ancalagon.transcript.transcript import Transcript
from ancalagon.workspace.workspace import Workspace


def _call(id: str, name: str, **arguments: str | int) -> ToolUse:
    return ToolUse(id=id, name=name, arguments=json.dumps(arguments))


INVESTIGATE = Role(behaviour="You investigate.", tools=(), budget=Budget(turns=5, tool_calls=5))


def _run(
    run_dir: pathlib.Path,
    task_dir: pathlib.Path,
    agent: int,
    replies: list[Reply],
) -> Outcome:
    spec = TaskSpec.model_validate_json((task_dir / "spec.json").read_text())
    transcript_path = task_dir / "transcript.jsonl"
    history: collections.abc.Sequence[Message] = (
        repair(load(transcript_path)) if transcript_path.exists() else []
    )
    ctx = ToolContext(
        workspace=Workspace(write_root=run_dir, read_roots=(run_dir,)),
        output_dir=task_dir / "tools",
        summary_chars=400,
        agent_id=agent,
    )
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=100 + agent)
    session = Session(
        spec=spec,
        input=FreeText(text="go"),
        messages=history,
        transcript=Transcript(path=transcript_path, agent_id=agent),
        agent_id=agent,
        llm=FakeLLM(replies),
        registry=Registry(
            [
                *delegate_tools(
                    {"investigate": INVESTIGATE}, run_dir=run_dir, parent=agent, clock=SystemClock()
                ),
                bind_tool(CheckTask(run_dir=run_dir, clock=SystemClock())),
                bind_tool(CollectTask(run_dir=run_dir, clock=SystemClock())),
                bind_tool(AnswerTask(run_dir=run_dir, parent=agent, clock=SystemClock())),
                bind_tool(NeedInput()),
                bind_tool(SubmitAnswer(FreeText)),
            ]
        ),
        ctx=ctx,
        output_class=FreeText,
        clock=SystemClock(),
    )
    outcome = session.run()
    (task_dir / f"outcome-{agent}.json").write_text(outcome.model_dump_json())
    bus.record(
        agent, AgentStatus(outcome.kind.value), EventSource.SUPERVISOR, summary=outcome.summary
    )
    return outcome


def _delegate(id: str, task_id: str, goal: str) -> ToolUse:
    return ToolUse(
        id=id,
        name="delegate_investigate",
        arguments=json.dumps({"task_id": task_id, "goal": goal, "input": {"text": "go"}}),
    )


def test_a_question_travels_to_the_root_and_the_answer_travels_back_down(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    run_dir = tmp_path / "run"
    root_dir = run_dir / "tasks" / "root"
    root_dir.mkdir(parents=True)
    (root_dir / "free_text.py").write_text(
        "import pydantic\n\n\nclass FreeText(pydantic.BaseModel):\n    text: str\n"
    )
    (root_dir / "spec.json").write_text(
        json.dumps(
            {
                "task_id": "root",
                "role": {
                    "behaviour": "You coordinate.",
                    "answer": {"module": "free_text.py", "name": "FreeText"},
                    "tools": [
                        "delegate_investigate",
                        "check_task",
                        "collect_task",
                        "answer_task",
                        "need_input",
                    ],
                    "budget": {"turns": 8, "tool_calls": 20},
                },
                "goal": "Investigate both halves.",
                "input": {"text": "go"},
            }
        )
    )
    migrate_file(run_dir / "bus.db", latest_version())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock())
    root = bus.enqueue(root_dir, parent_agent=0)

    first = _run(
        run_dir,
        root_dir,
        root,
        [
            Reply(
                blocks=[
                    _delegate("d1", "child-a", "The ambiguous half."),
                    _delegate("d2", "child-b", "The clear half."),
                ],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[_call("c1", "check_task", task=root + 1)],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[
                    _call(
                        "n1",
                        "need_input",
                        question="child-a asks: keep both captions or pick one?",
                    )
                ],
                stop_reason="tool_calls",
            ),
        ],
    )
    assert isinstance(first, NeedsInput)
    assert "keep both captions" in first.question

    child_a, child_b = root + 1, root + 2
    assert bus.dir_of(child_a) == str(run_dir / "tasks" / "child-a")

    asked = _run(
        run_dir,
        run_dir / "tasks" / "child-a",
        child_a,
        [
            Reply(
                blocks=[_call("n2", "need_input", question="keep both captions or pick one?")],
                stop_reason="tool_calls",
            )
        ],
    )
    assert isinstance(asked, NeedsInput)

    finished = _run(
        run_dir,
        run_dir / "tasks" / "child-b",
        child_b,
        [
            Reply(
                blocks=[_call("s1", "submit_answer", text="the clear half is fine")],
                stop_reason="tool_calls",
            )
        ],
    )
    assert isinstance(finished, Completed)

    assert answer_command(run_dir, root, "keep both") == 0
    assert f"answered agent {root}" in capsys.readouterr().out
    resumed_root = active_for(bus.snapshot(), str(root_dir))[0]

    history = load(root_dir / "transcript.jsonl")
    assert history[-1].blocks[0] == Text(text="keep both")

    second = _run(
        run_dir,
        root_dir,
        resumed_root,
        [
            Reply(
                blocks=[_call("g1", "collect_task", task=child_b)],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[_call("a1", "answer_task", task=child_a, answer="keep both")],
                stop_reason="tool_calls",
            ),
            Reply(
                blocks=[_call("s2", "submit_answer", text="both halves handled")],
                stop_reason="tool_calls",
            ),
        ],
    )
    assert isinstance(second, Completed)
    assert second.value.model_dump() == {"text": "both halves handled"}

    collected = (root_dir / "tools").glob("*collect_task*")
    assert any("the clear half is fine" in p.read_text() for p in collected)

    resumed_a = active_for(bus.snapshot(), str(run_dir / "tasks" / "child-a"))[0]
    assert resumed_a != child_a
    child_history = load(run_dir / "tasks" / "child-a" / "transcript.jsonl")
    assert child_history[-1].blocks[0] == Text(text="keep both")
    assert any(
        isinstance(b, ToolUse) and b.name == "need_input" for m in child_history for b in m.blocks
    )

    assert [e.status.value for e in bus.history(child_a)] == [
        "queued",
        "claimed",
        "running",
        "needs_input",
    ]
    assert [e.status.value for e in bus.history(resumed_a)] == ["queued"]
