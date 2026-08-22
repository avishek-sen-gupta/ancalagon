# Folds a run's lifecycle events and transcripts into one graph of what happened.
import collections.abc

from ancalagon.attempt.snapshot import Snapshot
from ancalagon.contracts.message import Message
from ancalagon.contracts.tool_result_block import ToolResultBlock
from ancalagon.contracts.tool_use import ToolUse
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.trace.agent_node import AgentNode
from ancalagon.trace.edge import Edge
from ancalagon.trace.edge_kind import EdgeKind
from ancalagon.trace.node_kind import NodeKind
from ancalagon.trace.node_ref import NodeRef
from ancalagon.trace.task_node import TaskNode
from ancalagon.trace.tool_call_node import ToolCallNode
from ancalagon.trace.trace import Trace

COLLECT = "collect_task"
UNANSWERED = ToolResultBlock(tool_use_id="", content="", path="")
ORDER = (
    EdgeKind.SPAWNED,
    EdgeKind.WOKE,
    EdgeKind.CALLED,
    EdgeKind.DELEGATED,
    EdgeKind.COLLECTED,
)

Uses = tuple[tuple[int, str, ToolUse], ...]
Messages = collections.abc.Mapping[int, collections.abc.Sequence[Message]]


def _task(id: int) -> NodeRef:
    return NodeRef(kind=NodeKind.TASK, id=id)


def _agent(id: int) -> NodeRef:
    return NodeRef(kind=NodeKind.AGENT, id=id)


def _uses(messages: collections.abc.Sequence[Message]) -> Uses:
    return tuple((m.agent, m.ts, b) for m in messages for b in m.blocks if isinstance(b, ToolUse))


def _results(
    messages: collections.abc.Sequence[Message],
) -> collections.abc.Mapping[str, ToolResultBlock]:
    return {b.tool_use_id: b for m in messages for b in m.blocks if isinstance(b, ToolResultBlock)}


def _all_uses(snapshot: Snapshot, messages: Messages) -> Uses:
    return tuple(use for task in snapshot.tasks for use in _uses(messages.get(task.id, ())))


def _agent_node(snapshot: Snapshot, task: int, agent: int) -> AgentNode:
    events = snapshot.events[agent]
    return AgentNode(
        id=agent,
        task=task,
        last_status=events[-1].status,
        started=events[0].ts,
        ended=events[-1].ts,
    )


def _agent_nodes(snapshot: Snapshot) -> tuple[AgentNode, ...]:
    return tuple(
        _agent_node(snapshot, task.id, agent)
        for task in snapshot.tasks
        for agent in snapshot.agents_by_task[task.id]
    )


def _call_nodes(snapshot: Snapshot, messages: Messages) -> tuple[ToolCallNode, ...]:
    answered = {
        use_id: result
        for task in snapshot.tasks
        for use_id, result in _results(messages.get(task.id, ())).items()
    }
    return tuple(
        ToolCallNode(
            id=number,
            agent=agent,
            name=use.name,
            ts=ts,
            ok=not answered.get(use.id, UNANSWERED).is_error,
            path=answered.get(use.id, UNANSWERED).path,
        )
        for number, (agent, ts, use) in enumerate(_all_uses(snapshot, messages), start=1)
    )


def _spawned(snapshot: Snapshot, started: collections.abc.Mapping[int, str]) -> list[Edge]:
    return [
        Edge(kind=EdgeKind.SPAWNED, source=_task(task.id), target=_agent(first), ts=started[first])
        for task in snapshot.tasks
        for first in snapshot.agents_by_task[task.id][:1]
    ]


def _woke(snapshot: Snapshot, started: collections.abc.Mapping[int, str]) -> list[Edge]:
    return [
        Edge(kind=EdgeKind.WOKE, source=_agent(before), target=_agent(after), ts=started[after])
        for task in snapshot.tasks
        for before, after in zip(
            snapshot.agents_by_task[task.id], snapshot.agents_by_task[task.id][1:], strict=False
        )
    ]


def _called(calls: tuple[ToolCallNode, ...]) -> list[Edge]:
    return [
        Edge(
            kind=EdgeKind.CALLED,
            source=_agent(call.agent),
            target=NodeRef(kind=NodeKind.TOOL_CALL, id=call.id),
            ts=call.ts,
        )
        for call in calls
    ]


def _delegated(snapshot: Snapshot) -> list[Edge]:
    return [
        Edge(
            kind=EdgeKind.DELEGATED,
            source=_agent(task.parent_agent),
            target=_task(task.id),
            ts=task.created,
        )
        for task in snapshot.tasks
        if task.parent_agent in snapshot.task_by_agent
    ]


def _collected(uses: Uses) -> list[Edge]:
    return [
        Edge(
            kind=EdgeKind.COLLECTED,
            source=_agent(agent),
            target=_task(TaskArgs.model_validate_json(use.arguments).task),
            ts=ts,
        )
        for agent, ts, use in uses
        if use.name == COLLECT
    ]


def _when(edge: Edge) -> tuple[str, int, int, int]:
    return (edge.ts, ORDER.index(edge.kind), edge.source.id, edge.target.id)


def graph_of(snapshot: Snapshot, messages: Messages) -> Trace:
    tasks = tuple(
        TaskNode(id=task.id, dir=task.dir, parent_agent=task.parent_agent)
        for task in snapshot.tasks
    )
    agents = _agent_nodes(snapshot)
    calls = _call_nodes(snapshot, messages)
    started = {agent.id: agent.started for agent in agents}
    edges = [
        *_spawned(snapshot, started),
        *_woke(snapshot, started),
        *_called(calls),
        *_delegated(snapshot),
        *_collected(_all_uses(snapshot, messages)),
    ]
    ordered = sorted((_when(edge), number) for number, edge in enumerate(edges))
    return Trace(
        nodes=(*tasks, *agents, *calls), edges=tuple(edges[number] for _, number in ordered)
    )
