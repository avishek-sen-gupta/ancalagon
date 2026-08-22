# Renders a trace as a Mermaid sequence diagram, one lane per task.
import collections.abc
import pathlib

from ancalagon.trace.agent_node import AgentNode
from ancalagon.trace.edge import Edge
from ancalagon.trace.edge_kind import EdgeKind
from ancalagon.trace.task_node import TaskNode
from ancalagon.trace.tool_call_node import ToolCallNode
from ancalagon.trace.trace import Trace
from ancalagon.viz.lanes import Lanes

HEADER = "sequenceDiagram"
INDENT = "    "


def _participants(tasks: collections.abc.Sequence[TaskNode]) -> list[str]:
    return [f"{INDENT}participant t{t.id} as {pathlib.PurePath(t.dir).name}" for t in tasks]


def _spawned(edge: Edge, lanes: Lanes) -> str:
    agent = lanes.agents[edge.target.id]
    return f"{INDENT}Note over t{agent.task}: agent {agent.id} starts"


def _woke(edge: Edge, lanes: Lanes) -> str:
    agent = lanes.agents[edge.target.id]
    return f"{INDENT}Note over t{agent.task}: agent {agent.id} wakes"


def _called(edge: Edge, lanes: Lanes) -> str:
    call = lanes.calls[edge.target.id]
    lane = lanes.agents[call.agent].task
    failed = "" if call.ok else " (failed)"
    return f"{INDENT}t{lane}->>t{lane}: {call.name}{failed}"


def _delegated(edge: Edge, lanes: Lanes) -> str:
    lane = lanes.agents[edge.source.id].task
    return f"{INDENT}t{lane}->>t{edge.target.id}: delegate"


def _collected(edge: Edge, lanes: Lanes) -> str:
    lane = lanes.agents[edge.source.id].task
    return f"{INDENT}t{lane}->>t{edge.target.id}: collect"


DRAWN: collections.abc.Mapping[EdgeKind, collections.abc.Callable[[Edge, Lanes], str]] = {
    EdgeKind.SPAWNED: _spawned,
    EdgeKind.WOKE: _woke,
    EdgeKind.CALLED: _called,
    EdgeKind.DELEGATED: _delegated,
    EdgeKind.COLLECTED: _collected,
}


def _ending(agent: AgentNode) -> tuple[str, str]:
    return (agent.ended, f"{INDENT}Note over t{agent.task}: agent {agent.id} {agent.last_status}")


def mermaid(trace: Trace) -> str:
    tasks = [n for n in trace.nodes if isinstance(n, TaskNode)]
    lanes = Lanes(
        agents={n.id: n for n in trace.nodes if isinstance(n, AgentNode)},
        calls={n.id: n for n in trace.nodes if isinstance(n, ToolCallNode)},
    )
    drawn = [(e.ts, DRAWN[e.kind](e, lanes)) for e in trace.edges]
    ended = [_ending(agent) for agent in lanes.agents.values()]
    body = [line for _, line in sorted([*drawn, *ended])]
    return "\n".join([HEADER, *_participants(tasks), *body])
