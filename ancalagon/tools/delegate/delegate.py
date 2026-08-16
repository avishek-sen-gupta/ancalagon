# Queues a subagent task and returns immediately; the supervisor spawns it.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.allowance import Allowance
from ancalagon.contracts.budget import Budget
from ancalagon.contracts.within_parent import WithinParent
from ancalagon.contracts.class_ref import ClassRef
from ancalagon.contracts.contract_source import ContractSource
from ancalagon.contracts.free_text_module import FREE_TEXT_FILE, FREE_TEXT_MODULE
from ancalagon.contracts.resolve import resolve_class
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class Delegate(Tool[DelegateArgs]):
    name = "delegate"
    description = (
        "Queue a subagent task. Returns its task id immediately without waiting. "
        "Reusing a task_id after that task has finished retries it, and the new agent "
        "inherits the previous one's transcript. Use a new task_id for a clean start."
    )
    cost = 1
    args_model = DelegateArgs

    def __init__(
        self,
        run_dir: pathlib.Path,
        parent: int,
        budget: Budget,
        clock: Clock,
        allowance: Allowance = WithinParent(),
    ):
        self.run_dir = run_dir
        self.parent = parent
        self.budget = budget
        self.clock = clock
        self.allowance = allowance

    def _install(
        self, source: ContractSource, task_dir: pathlib.Path, ctx: ToolContext
    ) -> ClassRef:
        if not source.path:
            (task_dir / FREE_TEXT_FILE).write_text(FREE_TEXT_MODULE)
            return ClassRef(module=str(task_dir / FREE_TEXT_FILE), name="FreeText")
        written = ctx.workspace.resolve_read(pathlib.Path(source.path))
        if not written.exists():
            raise ScopeError(f"no contract module at {written}")
        (task_dir / written.name).write_text(written.read_text())
        return ClassRef(module=str(task_dir / written.name), name=source.name)

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = Bus.open(self.run_dir / "bus.db", self.clock)
        active = bus.active_for(task_dir)
        if active:
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {active[0].status.value} as agent {active[0].agent}",
            )
        try:
            granted = self.allowance.grant(
                self.budget, Budget(turns=args.turns, tool_calls=args.tool_calls)
            )
        except ValueError as exc:
            return ctx.failure(self.name, str(exc))
        task_dir.mkdir(parents=True, exist_ok=True)
        try:
            given_in = self._install(args.contracts.input, task_dir, ctx)
            answers_in = self._install(args.contracts.answer, task_dir, ctx)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        try:
            input_class = resolve_class(given_in)
            given = input_class.model_validate_json(args.input_json)
        except (AttributeError, ImportError, TypeError, ValueError) as exc:
            return ctx.failure(self.name, f"input_json does not match {given_in.name}: {exc}")
        spec = AgentSpec[input_class](
            task_id=args.task_id,
            behaviour=args.behaviour,
            goal=args.goal,
            input=given,
            input_schema=given_in,
            answer_schema=answers_in,
            budget=granted,
        )
        (task_dir / "spec.json").write_text(spec.model_dump_json())
        task = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {task} for task {args.task_id} at {task_dir}")
