# Reports a delegated task's status without waiting.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool_context import ToolContext


class CheckTask:
    name = "check_task"
    description = "Report the status of a delegated task without waiting."

    def __init__(self, run_dir: pathlib.Path):
        self.run_dir = run_dir

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, TaskArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = TaskArgs.model_validate_json(arguments)
        try:
            row = Bus.open(self.run_dir / "bus.db").get(args.task)
        except KeyError as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(self.name, f"task {row.id} is {row.status.value}: {row.summary}")
