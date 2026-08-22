import pathlib
from collections.abc import Mapping, Sequence

import pytest


from ancalagon.attempt.attempt_of import attempt_of
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.lifecycle_store import HUMAN, LifecycleStore
from ancalagon.clock.fake_clock import FakeClock
from ancalagon.contracts.agent_event import AgentEvent
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.harness_task import HarnessTask
from ancalagon.contracts.message import Message
from ancalagon.contracts.message_role import MessageRole
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.fs.real_file_system import RealFileSystem
from ancalagon.migrations import latest_version, migrate_file
from ancalagon.trace.agent_node import AgentNode
from ancalagon.trace.edge import Edge
from ancalagon.trace.edge_kind import EdgeKind
from ancalagon.trace.graph_of import graph_of
from ancalagon.trace.node_kind import NodeKind
from ancalagon.trace.node_ref import NodeRef
from ancalagon.trace.task_node import TaskNode
from ancalagon.trace.tool_call_node import ToolCallNode
from ancalagon.trace.trace import Trace
from ancalagon.trace_command import trace_command
from ancalagon.viz.mermaid import mermaid
from ancalagon.viz_command import viz_command


def _snapshot(
    tasks: Sequence[tuple[int, str, int, str]],
    agents: Sequence[tuple[int, int]],
    events: Mapping[int, Sequence[tuple[int, str, AgentStatus, EventSource]]],
) -> Snapshot:
    built = {
        agent: tuple(
            AgentEvent(id=i, agent=agent, ts=ts, status=s, source=src, pid=0, summary="")
            for i, ts, s, src in rows
        )
        for agent, rows in events.items()
    }
    return Snapshot(
        tasks=tuple(HarnessTask(id=i, dir=d, parent_agent=p, created=c) for i, d, p, c in tasks),
        agents_by_task={t: tuple(a for a, owner in agents if owner == t) for t, _, _, _ in tasks},
        task_by_agent={a: t for a, t in agents},
        events=built,
        attempts={agent: attempt_of(found) for agent, found in built.items()},
    )


def _call(agent: int, seq: int, ts: str, use: str, name: str, arguments: str) -> Message:
    return Message(
        role=MessageRole.ASSISTANT,
        blocks=[ToolUse(id=use, name=name, arguments=arguments)],
        agent=agent,
        seq=seq,
        ts=ts,
    )


def _result(agent: int, seq: int, ts: str, use: str, path: str, failed: bool = False) -> Message:
    return Message(
        role=MessageRole.USER,
        blocks=[ToolResultBlock(tool_use_id=use, content="output", is_error=failed, path=path)],
        agent=agent,
        seq=seq,
        ts=ts,
    )


def _run() -> Snapshot:
    supervisor = EventSource.SUPERVISOR
    return _snapshot(
        tasks=[
            (1, "ws/runs/r_1/tasks/root", 0, "T00"),
            (2, "ws/runs/r_1/tasks/child", 1, "T03"),
        ],
        agents=[(1, 1), (2, 2), (5, 1)],
        events={
            1: [
                (1, "T01", AgentStatus.QUEUED, supervisor),
                (2, "T02", AgentStatus.CLAIMED, supervisor),
                (3, "T03", AgentStatus.RUNNING, supervisor),
                (4, "T08", AgentStatus.IDLING, supervisor),
            ],
            2: [
                (5, "T04", AgentStatus.QUEUED, supervisor),
                (6, "T05", AgentStatus.CLAIMED, supervisor),
                (7, "T06", AgentStatus.RUNNING, supervisor),
                (8, "T10", AgentStatus.EXHAUSTED, supervisor),
                (9, "T13", AgentStatus.COLLECTED, EventSource.WORKER),
            ],
            5: [
                (10, "T11", AgentStatus.QUEUED, supervisor),
                (11, "T11", AgentStatus.CLAIMED, supervisor),
                (12, "T11", AgentStatus.RUNNING, supervisor),
                (13, "T14", AgentStatus.COMPLETED, supervisor),
            ],
        },
    )


def _messages() -> Mapping[int, Sequence[Message]]:
    return {
        1: [
            _call(1, 1, "T04", "u1", "delegate_investigator", '{"task_id": "child"}'),
            _result(1, 2, "T04", "u1", "tools/0000-delegate_investigator.txt"),
            _call(1, 3, "T07", "u2", "idle", "{}"),
            _call(5, 4, "T12", "u3", "collect_task", '{"task": 2}'),
            _result(5, 5, "T12", "u3", "tools/0000-collect_task.txt"),
        ],
        2: [
            _call(2, 1, "T09", "u4", "shell", '{"command": "ls", "cwd": "."}'),
            _result(2, 2, "T09", "u4", "tools/0000-shell.err.txt", failed=True),
        ],
    }


def test_graph_of_a_run_carries_every_attempt_call_delegation_wake_and_collection():
    trace = graph_of(_run(), _messages())

    assert [n for n in trace.nodes if isinstance(n, TaskNode)] == [
        TaskNode(id=1, dir="ws/runs/r_1/tasks/root", parent_agent=0),
        TaskNode(id=2, dir="ws/runs/r_1/tasks/child", parent_agent=1),
    ]
    assert [n for n in trace.nodes if isinstance(n, AgentNode)] == [
        AgentNode(id=1, task=1, last_status=AgentStatus.IDLING, started="T01", ended="T08"),
        AgentNode(id=5, task=1, last_status=AgentStatus.COMPLETED, started="T11", ended="T14"),
        AgentNode(id=2, task=2, last_status=AgentStatus.COLLECTED, started="T04", ended="T13"),
    ]
    assert [n for n in trace.nodes if isinstance(n, ToolCallNode)] == [
        ToolCallNode(
            id=1,
            agent=1,
            name="delegate_investigator",
            ts="T04",
            ok=True,
            path="tools/0000-delegate_investigator.txt",
        ),
        ToolCallNode(id=2, agent=1, name="idle", ts="T07", ok=True, path=""),
        ToolCallNode(
            id=3,
            agent=5,
            name="collect_task",
            ts="T12",
            ok=True,
            path="tools/0000-collect_task.txt",
        ),
        ToolCallNode(
            id=4, agent=2, name="shell", ts="T09", ok=False, path="tools/0000-shell.err.txt"
        ),
    ]

    assert [
        (e.kind, e.source.kind, e.source.id, e.target.kind, e.target.id, e.ts) for e in trace.edges
    ] == [
        (EdgeKind.SPAWNED, NodeKind.TASK, 1, NodeKind.AGENT, 1, "T01"),
        (EdgeKind.DELEGATED, NodeKind.AGENT, 1, NodeKind.TASK, 2, "T03"),
        (EdgeKind.SPAWNED, NodeKind.TASK, 2, NodeKind.AGENT, 2, "T04"),
        (EdgeKind.CALLED, NodeKind.AGENT, 1, NodeKind.TOOL_CALL, 1, "T04"),
        (EdgeKind.CALLED, NodeKind.AGENT, 1, NodeKind.TOOL_CALL, 2, "T07"),
        (EdgeKind.CALLED, NodeKind.AGENT, 2, NodeKind.TOOL_CALL, 4, "T09"),
        (EdgeKind.WOKE, NodeKind.AGENT, 1, NodeKind.AGENT, 5, "T11"),
        (EdgeKind.CALLED, NodeKind.AGENT, 5, NodeKind.TOOL_CALL, 3, "T12"),
        (EdgeKind.COLLECTED, NodeKind.AGENT, 5, NodeKind.TASK, 2, "T12"),
    ]


def test_mermaid_renders_a_lane_per_task_and_every_edge_in_time_order():
    trace = Trace(
        nodes=(
            TaskNode(id=1, dir="ws/runs/r_1/tasks/root", parent_agent=0),
            TaskNode(id=2, dir="ws/runs/r_1/tasks/child", parent_agent=1),
            AgentNode(id=1, task=1, last_status=AgentStatus.IDLING, started="T01", ended="T08"),
            AgentNode(id=2, task=2, last_status=AgentStatus.EXHAUSTED, started="T04", ended="T10"),
            ToolCallNode(id=1, agent=1, name="list_dir", ts="T02", ok=True, path="p"),
            ToolCallNode(id=2, agent=2, name="shell", ts="T09", ok=False, path="p"),
        ),
        edges=(
            Edge(
                kind=EdgeKind.SPAWNED,
                source=NodeRef(kind=NodeKind.TASK, id=1),
                target=NodeRef(kind=NodeKind.AGENT, id=1),
                ts="T01",
            ),
            Edge(
                kind=EdgeKind.CALLED,
                source=NodeRef(kind=NodeKind.AGENT, id=1),
                target=NodeRef(kind=NodeKind.TOOL_CALL, id=1),
                ts="T02",
            ),
            Edge(
                kind=EdgeKind.DELEGATED,
                source=NodeRef(kind=NodeKind.AGENT, id=1),
                target=NodeRef(kind=NodeKind.TASK, id=2),
                ts="T03",
            ),
            Edge(
                kind=EdgeKind.SPAWNED,
                source=NodeRef(kind=NodeKind.TASK, id=2),
                target=NodeRef(kind=NodeKind.AGENT, id=2),
                ts="T04",
            ),
            Edge(
                kind=EdgeKind.CALLED,
                source=NodeRef(kind=NodeKind.AGENT, id=2),
                target=NodeRef(kind=NodeKind.TOOL_CALL, id=2),
                ts="T09",
            ),
        ),
    )

    assert mermaid(trace) == "\n".join(
        [
            "sequenceDiagram",
            "    participant t1 as root",
            "    participant t2 as child",
            "    Note over t1: agent 1 starts",
            "    t1->>t1: list_dir",
            "    t1->>t2: delegate",
            "    Note over t2: agent 2 starts",
            "    Note over t1: agent 1 idling",
            "    t2->>t2: shell (failed)",
            "    Note over t2: agent 2 exhausted",
        ]
    )


def test_trace_and_viz_commands_round_trip_through_a_file_and_through_stdout(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    fs = RealFileSystem()
    run_dir = tmp_path / "r_1"
    task_dir = run_dir / "tasks" / "root"
    fs.mkdir(task_dir, parents=True, exist_ok=True)
    migrate_file(run_dir / "bus.db", latest_version(fs), fs)
    clock = FakeClock()
    bus = LifecycleStore.open(run_dir / "bus.db", clock, fs)
    agent = bus.enqueue(task_dir, parent_agent=HUMAN)
    clock.sleep(1)
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR)
    called_at = clock.now().isoformat()
    clock.sleep(1)
    bus.record(agent, AgentStatus.COMPLETED, EventSource.SUPERVISOR)
    fs.write_text(
        task_dir / "transcript.jsonl",
        _call(agent, 1, called_at, "u1", "list_dir", "{}").model_dump_json() + "\n",
    )

    assert trace_command(run_dir, "", fs) == 0
    written = capsys.readouterr().out
    assert Trace.model_validate_json(written).edges[0].kind is EdgeKind.SPAWNED

    assert trace_command(run_dir, str(tmp_path / "trace.json"), fs) == 0
    assert viz_command(str(tmp_path / "trace.json"), "", fs) == 0
    assert capsys.readouterr().out.splitlines() == [
        "sequenceDiagram",
        "    participant t1 as root",
        f"    Note over t1: agent {agent} starts",
        "    t1->>t1: list_dir",
        f"    Note over t1: agent {agent} completed",
    ]
