# Reads a finished task's answer, or says why there is not one.
import pathlib

from ancalagon.attempt.attempt import Attempt
from ancalagon.attempt.closed import Closed
from ancalagon.attempt.collected import Collected
from ancalagon.attempt.lost import Lost
from ancalagon.attempt.snapshot import Snapshot
from ancalagon.bus.lifecycle_store import LifecycleStore
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
from ancalagon.fs.file_system import FileSystem
from ancalagon.schedule.addressed import addressed
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


def _unready(newest: int, attempt: Attempt) -> str:
    match attempt:
        case Collected(verdict=verdict):
            return f"agent {newest} was already collected: ended as {verdict.value}"
        case _:
            return f"agent {newest} has not been closed yet"


class CollectTask(Tool[TaskArgs]):
    name = "collect_task"
    description = (
        "Read a finished task's answer. Returns the answer itself, not a wrapper. "
        "Reports an error if the task is unfinished or did not produce one."
    )
    cost = 1
    args_model = TaskArgs

    def __init__(self, run_dir: pathlib.PurePath, clock: Clock, fs: FileSystem):
        self.run_dir = run_dir
        self.clock = clock
        self.fs = fs

    def run(self, args: TaskArgs, ctx: ToolContext) -> ToolResult:
        bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
        snapshot = bus.snapshot()
        if args.task not in snapshot.task_by_agent:
            return ctx.failure(self.name, f"no agent {args.task}")
        return self._answered(bus, ctx, snapshot, args.task)

    def _answered(
        self, bus: LifecycleStore, ctx: ToolContext, snapshot: Snapshot, asked: int
    ) -> ToolResult:
        task = snapshot.task_by_agent[asked]
        newest = addressed(snapshot, asked)
        match snapshot.attempts[newest]:
            case Closed():
                return self._read_closed(bus, ctx, snapshot, task, newest)
            case Lost(close=close):
                return self._read_lost(bus, ctx, snapshot, task, newest, close)
            case unsettled:
                return ctx.failure(self.name, _unready(newest, unsettled))

    def _read_closed(
        self, bus: LifecycleStore, ctx: ToolContext, snapshot: Snapshot, task: int, newest: int
    ) -> ToolResult:
        if not outstanding(snapshot, task):
            bus.record(newest, AgentStatus.COLLECTED, EventSource.WORKER)
        task_dir = pathlib.PurePath(task_of(snapshot, newest).dir)
        spec = TaskSpec.model_validate_json(self.fs.read_text(task_dir / "spec.json"))
        answer_class = resolve_class(spec.role.answer)
        outcome = outcome_adapter(answer_class).validate_json(
            self.fs.read_text(task_dir / f"outcome-{newest}.json")
        )
        if isinstance(outcome, (Completed, Exhausted)):
            return ctx.full_result(self.name, outcome.value.model_dump_json(), ".json")
        return ctx.failure(
            self.name, f"agent {newest} ended as {outcome.kind.value}: {_detail(outcome)}"
        )

    def _read_lost(
        self,
        bus: LifecycleStore,
        ctx: ToolContext,
        snapshot: Snapshot,
        task: int,
        newest: int,
        close: AgentStatus,
    ) -> ToolResult:
        if not outstanding(snapshot, task):
            bus.record(newest, AgentStatus.COLLECTED, EventSource.WORKER)
        closing = max(
            (event for event in snapshot.events[newest] if event.status is close),
            key=lambda event: event.id,
        )
        return ctx.failure(
            self.name,
            f"agent {newest} ended as {close.value}: {closing.summary}",
        )
