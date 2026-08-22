import json
import pathlib

import pytest

from ancalagon.answer import answer_task
from ancalagon.answer_command import answer_command
from ancalagon.attempt.queued import Queued
from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.system_clock import SystemClock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.task_of import task_of
from ancalagon.tools.delegate.answer_args import AnswerArgs
from ancalagon.tools.delegate.answer_task import AnswerTask
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.workspace import Workspace


def _ctx(tmp_path: pathlib.Path) -> ToolContext:
    write_root = tmp_path / "ws"
    write_root.mkdir(parents=True, exist_ok=True)
    return ToolContext(
        workspace=Workspace(RealFileSystem(), write_root=write_root, read_roots=(write_root,)),
        output_dir=write_root / "tools",
        summary_chars=200,
        agent_id=7,
    )


def _suspended(tmp_path: pathlib.Path) -> tuple[pathlib.Path, LifecycleStore, int]:
    run_dir = tmp_path / "run"
    task_dir = run_dir / "tasks" / "asked"
    task_dir.mkdir(parents=True)
    (task_dir / "transcript.jsonl").write_text(
        '{"role":"user","blocks":[{"kind":"text","text":"the goal"}],'
        '"agent":1,"seq":0,"ts":"t"}\n'
        '{"role":"assistant","blocks":[{"kind":"text","text":"asking"}],'
        '"agent":1,"seq":1,"ts":"t"}\n'
    )
    migrate_file(run_dir / "bus.db", latest_version(RealFileSystem()), RealFileSystem())
    bus = LifecycleStore.open(run_dir / "bus.db", SystemClock(), RealFileSystem())
    agent = bus.enqueue(task_dir, parent_agent=0)
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=1)
    return run_dir, bus, agent


def test_answering_a_suspended_agent_appends_the_answer_and_queues_a_new_attempt(
    tmp_path: pathlib.Path,
):
    run_dir, bus, agent = _suspended(tmp_path)
    task_dir = run_dir / "tasks" / "asked"

    with pytest.raises(ValueError, match="never asked"):
        answer_task(
            run_dir, agent, "too early", answered_by=0, clock=SystemClock(), fs=RealFileSystem()
        )

    bus.record(agent, AgentStatus.NEEDS_INPUT, EventSource.SUPERVISOR, summary="which one?")
    bus.record(agent, AgentStatus.COLLECTED, EventSource.WORKER)

    resumed = answer_task(
        run_dir, agent, "the second one", answered_by=0, clock=SystemClock(), fs=RealFileSystem()
    )
    assert resumed != agent

    lines = [json.loads(l) for l in (task_dir / "transcript.jsonl").read_text().splitlines()]
    assert len(lines) == 3
    assert [l["seq"] for l in lines] == [0, 1, 2]
    assert lines[2]["role"] == "user"
    assert lines[2]["blocks"][0]["text"] == "the second one"
    assert lines[2]["agent"] == 0
    assert lines[0]["blocks"][0]["text"] == "the goal"

    assert active_for(bus.snapshot(), str(task_dir)) == (resumed,)
    assert bus.attempt(resumed) == Queued()
    snap = bus.snapshot()
    assert task_of(snap, resumed).id == task_of(snap, agent).id
    assert task_of(snap, resumed).parent_agent == 0

    with pytest.raises(ValueError, match="never asked"):
        answer_task(
            run_dir, resumed, "again", answered_by=0, clock=SystemClock(), fs=RealFileSystem()
        )

    with pytest.raises(KeyError):
        answer_task(run_dir, 99, "nobody", answered_by=0, clock=SystemClock(), fs=RealFileSystem())


def test_the_tool_and_the_command_both_answer_and_report_what_they_queued(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    run_dir, bus, agent = _suspended(tmp_path)
    bus.record(agent, AgentStatus.NEEDS_INPUT, EventSource.SUPERVISOR, summary="which one?")
    ctx = _ctx(tmp_path)

    tool = AnswerTask(run_dir=run_dir, parent=7, clock=SystemClock(), fs=RealFileSystem())
    answered = tool.run(AnswerArgs(task=agent, answer="by tool"), ctx)
    assert answered.ok is True
    assert f"answered agent {agent}" in answered.summary.text_for_model()

    lines = [
        json.loads(l)
        for l in (run_dir / "tasks" / "asked" / "transcript.jsonl").read_text().splitlines()
    ]
    assert lines[-1]["blocks"][0]["text"] == "by tool"
    assert lines[-1]["agent"] == 7

    refused = tool.run(AnswerArgs(task=agent, answer="again"), ctx)
    assert refused.ok is False
    assert "already answered" in refused.error

    absent = tool.run(AnswerArgs(task=404, answer="nobody"), ctx)
    assert absent.ok is False

    second, other_bus, other = _suspended(tmp_path / "other")
    other_bus.record(other, AgentStatus.NEEDS_INPUT, EventSource.SUPERVISOR, summary="q")
    assert answer_command(second, other, "by command") == 0
    assert f"answered agent {other}" in capsys.readouterr().out
