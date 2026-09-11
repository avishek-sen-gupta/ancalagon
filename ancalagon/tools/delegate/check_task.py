# Reports a delegated task's status without waiting, as of the agent serving it now.
from ancalagon.bus.bus import Bus
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.schedule.addressed import addressed
from ancalagon.schedule.latest_event import latest_event
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class CheckTask(Tool[TaskArgs]):
    name = "check_task"
    description = "Report the status of a delegated task without waiting. This does not consume your tool-call budget."
    cost = 0
    args_model = TaskArgs

    def __init__(self, bus: Bus):
        self.bus = bus

    def run(self, args: TaskArgs, ctx: ToolContext) -> ToolResult:
        snapshot = self.bus.snapshot()
        if args.task not in snapshot.task_by_agent:
            return ctx.failure(self.name, f"no agent {args.task}")
        newest = addressed(snapshot, args.task)
        latest = latest_event(snapshot, newest)
        return ctx.result(
            self.name,
            f"its newest agent is {newest}, which is {latest.status.value}: {latest.summary}",
        )
