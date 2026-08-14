# Queues a subagent task and returns immediately; the supervisor spawns it.
import json
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.free_text_module import FREE_TEXT_MODULE
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool_context import ToolContext


class Delegate:
    name = "delegate"
    description = (
        "Queue a subagent task. Returns its task id immediately without waiting. "
        "Reusing a task_id after that task has finished retries it, and the new agent "
        "inherits the previous one's transcript. Use a new task_id for a clean start."
    )
    cost = 1

    def __init__(self, run_dir: pathlib.Path, parent: int):
        self.run_dir = run_dir
        self.parent = parent

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, DelegateArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = DelegateArgs.model_validate_json(arguments)
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = Bus.open(self.run_dir / "bus.db")
        active = bus.active_for(task_dir)
        if active:
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {active[0].status.value} as agent {active[0].agent}",
            )
        try:
            json.loads(args.input_json)
        except json.JSONDecodeError as exc:
            return ctx.failure(self.name, f"input_json is not valid JSON: {exc}")
        if args.contracts_path:
            try:
                source = ctx.workspace.resolve_read(pathlib.Path(args.contracts_path))
            except ScopeError as exc:
                return ctx.failure(self.name, str(exc))
            if not source.exists():
                return ctx.failure(self.name, f"no contracts file at {source}")
            contracts = source.read_text()
        else:
            contracts = FREE_TEXT_MODULE
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
        (task_dir / "contracts.py").write_text(contracts)
        task = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {task} for task {args.task_id} at {task_dir}")
