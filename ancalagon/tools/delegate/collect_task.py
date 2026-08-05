# Reads a finished task's answer, or says why there is not one.
import json
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool_context import ToolContext


class CollectTask:
    name = "collect_task"
    description = (
        "Read a finished task's answer. Returns the answer itself, not a wrapper. "
        "Reports an error if the task is unfinished or did not produce one."
    )
    cost = 1

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
        outcome = pathlib.Path(row.dir) / "outcome.json"
        if not outcome.exists():
            return ctx.failure(self.name, f"task {row.id} is {row.status.value}, no outcome yet")
        parsed = json.loads(outcome.read_text())
        if "value" in parsed:
            return ctx.result(self.name, json.dumps(parsed["value"]), ".json")
        detail = parsed.get("detail") or parsed.get("error") or parsed.get("summary", "")
        return ctx.failure(self.name, f"task {row.id} ended as {parsed['kind']}: {detail}")
