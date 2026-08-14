# Reads a finished task's answer, or says why there is not one.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.exhausted import Exhausted
from ancalagon.contracts.failed import Failed
from ancalagon.contracts.needs_input import NeedsInput
from ancalagon.contracts.outcome import Outcome, outcome_adapter
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.delegate.task_args import TaskArgs
from ancalagon.tools.registry.tool_context import ToolContext


def _detail(outcome: Outcome) -> str:
    if isinstance(outcome, NeedsInput):
        return outcome.question
    if isinstance(outcome, Failed):
        return outcome.error
    return outcome.summary


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
            state = Bus.open(self.run_dir / "bus.db").state(args.task)
        except KeyError as exc:
            return ctx.failure(self.name, str(exc))
        task_dir = pathlib.Path(state.dir)
        written = task_dir / "outcome.json"
        if not written.exists():
            return ctx.failure(
                self.name, f"agent {state.agent} is {state.status.value}, no outcome yet"
            )
        spec = TaskSpec.model_validate_json((task_dir / "spec.json").read_text())
        answer_class = resolve_class(spec.answer_schema, task_dir)
        outcome = outcome_adapter(answer_class).validate_json(written.read_text())
        if isinstance(outcome, (Completed, Exhausted)):
            return ctx.result(self.name, outcome.value.model_dump_json(), ".json")
        return ctx.failure(
            self.name, f"agent {state.agent} ended as {outcome.kind.value}: {_detail(outcome)}"
        )
