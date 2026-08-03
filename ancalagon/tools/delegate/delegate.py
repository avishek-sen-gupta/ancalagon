import json
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool_context import ToolContext


class Delegate:
    name = "delegate"
    description = "Queue a subagent task. Returns its task id immediately without waiting."

    def __init__(self, run_dir: pathlib.Path, parent: int):
        self.run_dir = run_dir
        self.parent = parent

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, DelegateArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = DelegateArgs.model_validate_json(arguments)
        task_dir = self.run_dir / "tasks" / args.task_id
        if (task_dir / "spec.json").exists():
            return ctx.failure(self.name, f"task {args.task_id} already exists at {task_dir}")
        try:
            json.loads(args.input_json)
        except json.JSONDecodeError as exc:
            return ctx.failure(self.name, f"input_json is not valid JSON: {exc}")
        task_dir.mkdir(parents=True, exist_ok=True)
        scalars: dict[str, str] = {
            "task_id": args.task_id,
            "behaviour": args.behaviour,
            "goal": args.goal,
            "output": args.output,
        }
        head = ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in scalars.items())
        spec_text = (
            "{"
            + head
            + f', "input": {args.input_json}'
            + f', "budget": {{"turns": {args.turns}, "tool_calls": {args.tool_calls}}}'
            + ', "tools": []}'
        )
        (task_dir / "spec.json").write_text(spec_text)
        (task_dir / "contracts.py").write_text(args.contracts_py or FREE_TEXT_MODULE)
        task = Bus.open(self.run_dir / "bus.db").enqueue(task_dir, parent=self.parent)
        return ctx.result(self.name, f"queued task {task} at {task_dir}")
