# Reports a delegated task's status without waiting.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class CheckTask(Tool[TaskArgs]):
    name = "check_task"
    description = "Report the status of a delegated task without waiting. This does not consume your tool-call budget."
    cost = 0
    args_model = TaskArgs

    def __init__(self, run_dir: pathlib.Path, clock: Clock):
        self.run_dir = run_dir
        self.clock = clock

    def run(self, args: TaskArgs, ctx: ToolContext) -> ToolResult:
        try:
            state = Bus.open(self.run_dir / "bus.db", self.clock).state(args.task)
        except KeyError as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(
            self.name, f"agent {state.agent} is {state.status.value}: {state.summary}"
        )
