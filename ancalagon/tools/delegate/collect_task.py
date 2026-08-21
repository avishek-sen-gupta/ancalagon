# Reads a finished task's answer, or says why there is not one.
import pathlib

from ancalagon.attempt.closed import Closed
from ancalagon.attempt.collected import Collected
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.event_source import EventSource
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import Outcome, outcome_adapter
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.schedule.outstanding import outstanding
from ancalagon.schedule.task_of import task_of
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


def _detail(outcome: Outcome) -> str:
    if isinstance(outcome, NeedsInput):
        return outcome.question
    if isinstance(outcome, Failed):
        return outcome.error
    return outcome.summary


class CollectTask(Tool[TaskArgs]):
    name = "collect_task"
    description = (
        "Read a finished task's answer. Returns the answer itself, not a wrapper. "
        "Reports an error if the task is unfinished or did not produce one."
    )
    cost = 1
    args_model = TaskArgs

    def __init__(self, run_dir: pathlib.Path, clock: Clock):
        self.run_dir = run_dir
        self.clock = clock

    def run(self, args: TaskArgs, ctx: ToolContext) -> ToolResult:
        bus = Bus.open(self.run_dir / "bus.db", self.clock)
        snapshot = bus.snapshot()
        if args.task not in snapshot.task_by_agent:
            return ctx.failure(self.name, f"no agent {args.task}")
        task = snapshot.task_by_agent[args.task]
        newest = newest_agent(snapshot, task)
        attempt = snapshot.attempts[newest]
        match attempt:
            case Collected(verdict=verdict):
                return ctx.failure(
                    self.name,
                    f"agent {newest} was already collected: ended as {verdict.value}",
                )
            case Closed():
                return self._read_closed(bus, ctx, snapshot, task, newest)
            case Lost(close=close):
                return self._read_lost(bus, ctx, snapshot, task, newest, close)
            case _:
                return ctx.failure(self.name, f"agent {newest} has not been closed yet")

    def _read_closed(
        self, bus: Bus, ctx: ToolContext, snapshot: Snapshot, task: int, newest: int
    ) -> ToolResult:
        still_outstanding = outstanding(snapshot, task)
        task_dir = pathlib.Path(task_of(snapshot, newest).dir)
        spec = TaskSpec.model_validate_json((task_dir / "spec.json").read_text())
        answer_class = resolve_class(spec.role.answer)
        outcome = outcome_adapter(answer_class).validate_json(
            (task_dir / f"outcome-{newest}.json").read_text()
        )
        if not still_outstanding:
            bus.record(newest, AgentStatus.COLLECTED, EventSource.WORKER)
        if isinstance(outcome, (Completed, Exhausted)):
            return ctx.full_result(self.name, outcome.value.model_dump_json(), ".json")
        return ctx.failure(
            self.name, f"agent {newest} ended as {outcome.kind.value}: {_detail(outcome)}"
        )

    def _read_lost(
        self,
        bus: Bus,
        ctx: ToolContext,
        snapshot: Snapshot,
        task: int,
        newest: int,
        close: AgentStatus,
    ) -> ToolResult:
        still_outstanding = outstanding(snapshot, task)
        closing = next(
            event for event in reversed(snapshot.events[newest]) if event.status is close
        )
        if not still_outstanding:
            bus.record(newest, AgentStatus.COLLECTED, EventSource.WORKER)
        return ctx.failure(
            self.name,
            f"agent {newest} ended as {close.value}: {closing.summary}",
        )
